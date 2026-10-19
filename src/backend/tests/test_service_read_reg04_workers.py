"""REG04 INCR-2: AFI dual worker processes plus one strategy run on one owner.

Real HTTP (two spawned AFI app processes running the production lifespan and
per-subject SDK owner-thread workers), the real SDK CURVE transport and one
spawned Execution ServiceHost account owner (the AFI07 combined-owner fixture)
prove, as actual behavior instead of YAML:

1. Two AFI app processes (two JWT subjects, distinct SDK client sessions and
   process IDs) operate while one strategy run holds its single-active
   ``strategy_write_claims`` entry: application workers never create or consume
   that claim, a second strategy run is rejected with ``DUPLICATE_ACTIVE_RUN``
   while the workers continue, and newly registering workers are admitted while
   the claim is live.
2. Exactly-once dispatch per accepted operation across the two workers
   (including one same-key submission fired concurrently at both processes),
   with durable principal/actor/delegate attribution per intent in the
   operation tables, the journal and the owner-side service-call log.
3. One stable manual-book attribution for every worker session/user name (the
   SDK registry shows the same ``manual_book_ref`` on both worker sessions) and
   the honest quota facts the machinery exposes: one admission reservation per
   accepted operation, no reservation for replays, and one deduplicated group
   budget reservation.
4. Ordinary worker operations leave the reserved group-leg namespace
   byte-identical (existing group snapshot/event-log helpers).

Test-only: no production module is changed.  The heavy fixtures (combined
owner host, deployment profiles, spawned app process, operation-row readers,
group snapshot helper) are reused from
``tests.test_service_read_authorized_http_integration``; only the REG04 nodes
and thin HTTP/registry projections are new.  This file must run with the fixed
frozen-SDK QA environment (see the REG04 evidence bundle).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import multiprocessing
import os
import sqlite3
import time
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from tests import test_service_read_authorized_http_integration as _afi07

_order = _afi07._order

_JWT_SECRET = _afi07._JWT_SECRET
_DOMAIN = _afi07._DOMAIN
_SUBJECT_A = _afi07._SUBJECT_A
_SUBJECT_B = _afi07._SUBJECT_B
_DELEGATE_A = _afi07._DELEGATE_A
_DELEGATE_B = _afi07._DELEGATE_B
_ACCOUNT_A = _afi07._ACCOUNT_A
_STRATEGY_A = _afi07._STRATEGY_A
_STRATEGY_B = _afi07._STRATEGY_B
_APP_PRINCIPAL = _afi07._APP_PRINCIPAL
_STRATEGY_B_PRINCIPAL = _afi07._STRATEGY_B_PRINCIPAL
_APPLICATION_IDENTITY_B = _afi07._APPLICATION_IDENTITY_B
_MANUAL_SUBMIT_SELECTOR = _afi07._MANUAL_SUBMIT_SELECTOR
_MANUAL_BOOK_A = _afi07._MANUAL_BOOK_A
_MANUAL_SCOPE_A = _afi07._MANUAL_SCOPE_A
_APPROVED_TARGET_SELECTOR = _afi07._APPROVED_TARGET_SELECTOR
_APPROVED_TARGET_EXPECTED_SCOPE = _afi07._APPROVED_TARGET_EXPECTED_SCOPE
_APPROVED_TARGET_POLICY_REF = _afi07._APPROVED_TARGET_POLICY_REF
_STRATEGY_B_IDENTITY = _afi07._STRATEGY_B_IDENTITY
_STRATEGY_B_GRANT_SCOPE = _afi07._STRATEGY_B_GRANT_SCOPE
_COMMAND_GUARD_STATE = _afi07._COMMAND_GUARD_STATE

_WireRole = _afi07.WireRole

_REG04_AUTHORITY_DB = "reg04-shared-authority.sqlite3"
_OWNER_REGISTRY_FILE = "afi07-owner-registry.sqlite3"
_OWNER_EXECUTION_FILE = "afi07-owner-execution.sqlite3"
_APP_LABEL_1 = "afi07-manual-order-app-1"
_APP_LABEL_2 = "afi07-manual-order-app-2"

# Node 1: dual-worker scenario.
_REG04_DUAL_MANUAL_KEY_FIRST = "reg04-dual-worker-manual-first-key"
_REG04_DUAL_MANUAL_KEY_SHARED = "reg04-dual-worker-manual-shared-key"
_REG04_DUAL_MANUAL_KEY_SECOND = "reg04-dual-worker-manual-second-key"
_REG04_DUAL_APPROVED_KEY = "reg04-dual-worker-approved-submit-key"
_REG04_DUAL_MANUAL_KEY_UNDER_CLAIM = "reg04-dual-worker-manual-under-claim-key"
_REG04_DUAL_MANUAL_KEY_AFTER_REJECTION = "reg04-dual-worker-manual-after-rejection-key"
_REG04_DUAL_STRATEGY_INTENT_1 = "reg04-strategy-direct-intent-1"
_REG04_DUAL_STRATEGY_INTENT_2 = "reg04-strategy-direct-intent-2"

# Node 2: worker registration under a live strategy claim.
_REG04_LATE_MANUAL_KEY = "reg04-late-worker-manual-key"
_REG04_LATE_APPROVED_KEY = "reg04-late-worker-approved-submit-key"
_REG04_LATE_STRATEGY_INTENT_1 = "reg04-late-strategy-direct-intent-1"
_REG04_LATE_STRATEGY_INTENT_2 = "reg04-late-strategy-direct-intent-2"

_MANUAL_SUBMIT_PATH = "/api/v1/service-orders/manual"
_APPROVED_TARGETS_PATH = "/api/v1/service-orders/approved-targets"
_APPROVED_SUBMIT_PATH = "/api/v1/service-orders/approved-targets/submit"


def _reg04_owner_keys(engine: Any) -> dict[str, Any]:
    """Build the curve-key/material bundle shared by owner, apps and runtimes."""

    server_public, server_secret = _afi07.zmq.curve_keypair()
    application_public, application_secret = _afi07.zmq.curve_keypair()
    strategy_b_public, strategy_b_secret = _afi07.zmq.curve_keypair()
    return {
        "server_public": server_public,
        "server_secret": server_secret,
        "application_public": application_public,
        "application_secret": application_secret,
        "strategy_b_public": strategy_b_public,
        "strategy_b_secret": strategy_b_secret,
        "database_url": str(engine.url),
    }


def _reg04_deployment_json(endpoint: str, keys: dict[str, Any]) -> str:
    """Trusted deployment for one manual worker (B) and one approved worker (A)."""

    return json.dumps(
        {
            "schema_version": 1,
            "subjects": [
                _afi07._manual_order_deployment_profile(
                    endpoint=endpoint,
                    subject=_SUBJECT_B,
                    identity=_APPLICATION_IDENTITY_B,
                    account_ref=_ACCOUNT_A,
                    manual_book_ref=_MANUAL_BOOK_A,
                    manual_scope=_MANUAL_SCOPE_A,
                    security_ref="reg04-manual-b-curve-v1",
                    keys=keys,
                ),
                _afi07._approved_target_deployment_profile(endpoint=endpoint, keys=keys),
            ],
        }
    )


def _reg04_registry_facts(registry_path: str) -> dict[str, Any]:
    """Project the durable SDK registry (read-only) into finite test facts."""

    uri = Path(registry_path).resolve().as_uri() + "?mode=ro"
    claims: list[dict[str, Any]] = []
    sessions: list[dict[str, Any]] = []
    live_sessions = 0
    deadline = time.monotonic() + 20.0
    while True:
        connection = None
        try:
            connection = sqlite3.connect(uri, uri=True, timeout=5.0)
            connection.row_factory = sqlite3.Row
            claims = [
                {
                    "execution_domain_ref": row["execution_domain_ref"],
                    "strategy_ref": row["strategy_ref"],
                    "account_ref": row["account_ref"],
                    "run_id": row["run_id"],
                    "active_registration_id": row["active_registration_id"],
                }
                for row in connection.execute(
                    "SELECT execution_domain_ref, strategy_ref, account_ref, run_id, "
                    "active_registration_id FROM strategy_write_claims "
                    "ORDER BY strategy_ref, account_ref"
                )
            ]
            now = time.time()
            live_sessions = 0
            sessions = []
            for row in connection.execute(
                "SELECT registration_id, principal, identity_json, scope_ref, scope_json, "
                "operations_json, write_operations_json, expires_at FROM sessions "
                "ORDER BY registration_id"
            ):
                identity = json.loads(row["identity_json"])
                scope = json.loads(row["scope_json"])
                assert type(identity) is dict and type(scope) is dict
                if row["expires_at"] > now:
                    live_sessions += 1
                sessions.append(
                    {
                        "registration_id": row["registration_id"],
                        "principal": row["principal"],
                        "identity": identity,
                        "scope_ref": row["scope_ref"],
                        "scope": scope,
                        "operations": sorted(json.loads(row["operations_json"])),
                        "write_operations": sorted(json.loads(row["write_operations_json"])),
                    }
                )
            break
        except sqlite3.OperationalError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.1)
        finally:
            if connection is not None:
                connection.close()
    return {
        "claims": tuple(claims),
        "sessions": tuple(sessions),
        "live_sessions": live_sessions,
    }


def _reg04_start_app_server(
    context: Any, *, database_url: str, deployment_json: str, label: str
) -> dict[str, Any]:
    """Spawn one real AFI app process (uvicorn + production lifespan) and wait."""

    server = _afi07._start_manual_order_http_app_process(
        context, database_url=database_url, deployment_json=deployment_json, label=label
    )
    ready = _afi07._receive_manual_order_app_message(server)
    assert ready[0] == "ready", ready
    server["ready"] = ready
    return server


def _reg04_stop_app_servers(
    servers: list[dict[str, Any]], *, expected_workers: int
) -> list[BaseException]:
    """Gracefully close app processes; adaptation of the established stopper
    with the worker count parameterized (two trusted subject workers each)."""

    failures: list[BaseException] = []
    for server in servers:
        try:
            receipt, cleanup = _afi07._stop_manual_order_http_app_process(server)
            server["close_receipt"] = receipt
            server["cleanup"] = cleanup
            if cleanup["failures"]:
                failures.append(AssertionError((server["label"], cleanup)))
            if not isinstance(receipt, tuple) or receipt[0] != "closed":
                failures.append(AssertionError((server["label"], "missing_close_receipt")))
            elif not all(receipt[2][:5]):
                failures.append(AssertionError((server["label"], "lifespan_cleanup_incomplete")))
            elif receipt[1] != (server.get("ready") or (None, None))[1]:
                failures.append(AssertionError((server["label"], "close_pid_mismatch")))
            elif receipt[2][5] != expected_workers:
                failures.append(
                    AssertionError((server["label"], "owner_worker_count_mismatch"))
                )
            if cleanup["terminate_attempted"]:
                failures.append(AssertionError((server["label"], "forced_termination_used")))
        except BaseException as error:
            server["stop_error"] = type(error).__name__
            failures.append(error)
    return failures


async def _reg04_http_post(
    port: int,
    path: str,
    body: dict[str, Any],
    *,
    token: str,
    idempotency_key: str | None = None,
) -> Any:
    import httpx

    headers = {"Authorization": f"Bearer {token}"}
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    async with httpx.AsyncClient(timeout=20.0) as client:
        return await client.post(f"http://127.0.0.1:{port}{path}", json=body, headers=headers)


def _reg04_require_ok(response: Any, *, label: str) -> None:
    details_code = None
    try:
        payload = response.json()
    except (TypeError, ValueError):
        payload = None
    if isinstance(payload, dict):
        details = payload.get("details", payload.get("detail"))
        if isinstance(details, dict):
            details_code = details.get("code")
    assert response.status_code == 200, (
        label,
        response.status_code,
        payload.get("error") if isinstance(payload, dict) else None,
        details_code,
    )


async def _reg04_manual_submit(
    port: int, *, token: str, key: str, label: str
) -> dict[str, Any]:
    """One HTTP manual submit; server-side attribution must stay book A."""

    response = await _reg04_http_post(
        port,
        _MANUAL_SUBMIT_PATH,
        dict(_afi07._AFI07_MANUAL_ORDER_BODY),
        token=token,
        idempotency_key=key,
    )
    _reg04_require_ok(response, label=label)
    payload = response.json()
    assert payload["record"]["state"] == "ACKED", label
    assert payload["actor_ref"] == _SUBJECT_B, label
    assert payload["delegate_ref"] == _DELEGATE_B, label
    assert payload["account_ref"] == _ACCOUNT_A, label
    assert payload["manual_book_ref"] == _MANUAL_BOOK_A, label
    return payload


async def _reg04_manual_concurrent_pair(
    port1: int, port2: int, *, token: str, key: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Fire one same-key submission at both worker processes at once."""

    start_barrier = asyncio.Barrier(2)

    async def submit(port: int) -> dict[str, Any]:
        await start_barrier.wait()
        return await _reg04_manual_submit(port, token=token, key=key, label=f"shared:{port}")

    first, second = await asyncio.gather(submit(port1), submit(port2))
    assert first["intent_id"] == second["intent_id"]
    assert first["record"]["provider_order_id"] == second["record"]["provider_order_id"]
    return first, second


async def _reg04_approved_submit_flow(
    *,
    publish_port: int,
    create_port: int,
    submit_port: int,
    replay_port: int,
    token: str,
    operation_key: str,
    observed: dict[str, Any],
) -> None:
    """Reuse the established approved-target HTTP flow across given workers."""

    policy = {
        "schema_id": "afi.strategy_order_approval_policy",
        "schema_version": 1,
        "allowed_instruments": ["BTC-USDT"],
        "allowed_sides": ["BUY", "SELL"],
        "allowed_position_effects": ["OPEN", "CLOSE", "CLOSE_TODAY", "CLOSE_YESTERDAY"],
        "allowed_order_types": ["LIMIT"],
        "allowed_time_in_force": ["GTC"],
        "limits": {
            "max_quantity": "2",
            "max_notional": "200",
            "min_price": "1",
            "max_price": "200",
        },
    }
    publish = await _reg04_http_post(
        publish_port,
        f"{_APPROVED_TARGETS_PATH}/policies/{_APPROVED_TARGET_POLICY_REF}",
        {"policy": policy},
        token=token,
    )
    assert publish.status_code == 201, (
        "approved-policy-publish",
        publish.status_code,
        _afi07._approved_target_http_fact(publish),
    )
    create_body = {
        "scope_ref": _APPROVED_TARGET_SELECTOR,
        "strategy_version": 7,
        "instrument": "BTC-USDT",
        "metadata_version": "instrument-v1",
        "side": "BUY",
        "position_effect": "OPEN",
        "order_type": "LIMIT",
        "quantity": "1",
        "price": "100",
        "time_in_force": "GTC",
        "reduce_only": False,
        "expires_in_seconds": 600,
    }
    created = await _reg04_http_post(
        create_port, _APPROVED_TARGETS_PATH, create_body, token=token
    )
    assert created.status_code == 201, (
        "approved-target-create",
        created.status_code,
        _afi07._approved_target_http_fact(created),
    )
    approved = created.json()
    submit_body = {
        "scope_ref": _APPROVED_TARGET_SELECTOR,
        "approval_ref": approved["approval_ref"],
        "approval_version": approved["approval_version"],
        "target_sha256": approved["target_sha256"],
    }
    first = await _reg04_http_post(
        submit_port,
        _APPROVED_SUBMIT_PATH,
        submit_body,
        token=token,
        idempotency_key=operation_key,
    )
    _reg04_require_ok(first, label="approved-submit")
    replay = await _reg04_http_post(
        replay_port,
        _APPROVED_SUBMIT_PATH,
        submit_body,
        token=token,
        idempotency_key=operation_key,
    )
    _reg04_require_ok(replay, label="approved-replay")
    payload = first.json()
    assert replay.json()["intent_id"] == payload["intent_id"]
    assert payload["operation_kind"] == "approved_strategy_target"
    assert payload["record"]["state"] == "ACKED"
    observed["approved_intent"] = payload["intent_id"]
    observed["approved_order"] = payload["record"]["provider_order_id"]


def _reg04_strategy_runtime(endpoint: str, keys: dict[str, Any]) -> Any:
    return _afi07._new_runtime(
        endpoint,
        role="strategy_client",
        security_ref=_afi07._AFI07_STRATEGY_SECURITY_REF,
        keys=keys,
        identity=_STRATEGY_B_IDENTITY,
        scope_ref=_afi07._AFI07_STRATEGY_SELECTOR,
        scope=_STRATEGY_B_GRANT_SCOPE,
    )


def _reg04_strategy_submit(client: Any, intent_id: str) -> Any:
    from decimal import Decimal

    return client.submit(
        intent_id=intent_id,
        signal_id=f"{intent_id}-signal",
        instrument="BTC-USDT",
        side="BUY",
        position_effect="OPEN",
        order_type="LIMIT",
        quantity=Decimal("1"),
        price=Decimal("50000"),
        time_in_force="GTC",
        reduce_only=False,
        metadata_version="reg04-direct-v1",
    )


def _reg04_assert_single_live_claim(
    registry: dict[str, Any], *, expect_sessions: int
) -> dict[str, Any]:
    """Assert exactly one live strategy claim held by one strategy session."""

    claims = registry["claims"]
    assert len(claims) == 1, claims
    claim = claims[0]
    assert claim["execution_domain_ref"] == _STRATEGY_B_GRANT_SCOPE.execution_domain_ref
    assert claim["strategy_ref"] == _STRATEGY_B
    assert claim["account_ref"] == _ACCOUNT_A
    assert type(claim["run_id"]) is str and claim["run_id"]
    assert claim["active_registration_id"] is not None
    sessions = registry["sessions"]
    assert len(sessions) == expect_sessions, [s["registration_id"] for s in sessions]
    assert registry["live_sessions"] == expect_sessions
    holders = [
        session
        for session in sessions
        if session["registration_id"] == claim["active_registration_id"]
    ]
    assert len(holders) == 1
    holder = holders[0]
    assert holder["identity"]["role"] == _WireRole.STRATEGY_CLIENT.value
    assert holder["identity"]["principal_ref"] == _STRATEGY_B_PRINCIPAL
    assert holder["identity"]["actor_ref"] == _STRATEGY_B
    assert holder["identity"]["delegate_ref"] in (None, "")
    application_sessions = [
        session
        for session in sessions
        if session["identity"]["role"] == _WireRole.APPLICATION_CLIENT.value
    ]
    assert all(
        session["principal"] == _APP_PRINCIPAL for session in application_sessions
    )
    assert claim["active_registration_id"] not in {
        session["registration_id"] for session in application_sessions
    }
    return claim


def _reg04_assert_application_sessions(
    registry: dict[str, Any], *, expected_actor_counts: dict[str, int]
) -> None:
    """Application workers hold no claim and stay attributed to trusted books."""

    application_sessions = [
        session
        for session in registry["sessions"]
        if session["identity"]["role"] == _WireRole.APPLICATION_CLIENT.value
    ]
    counts = Counter(
        session["identity"]["actor_ref"] for session in application_sessions
    )
    assert dict(counts) == expected_actor_counts, counts
    assert len({session["registration_id"] for session in application_sessions}) == sum(
        expected_actor_counts.values()
    )
    for session in application_sessions:
        assert session["principal"] == _APP_PRINCIPAL
        assert session["identity"]["principal_ref"] == _APP_PRINCIPAL
        identity = session["identity"]
        scope = session["scope"]
        if identity["actor_ref"] == _SUBJECT_B:
            assert scope["manual_book_ref"] == _MANUAL_BOOK_A
            assert scope["account_ref"] == _ACCOUNT_A
            assert scope["strategy_ref"] is None
            assert session["scope_ref"] == _MANUAL_SUBMIT_SELECTOR
            assert "orders.submit" in session["write_operations"]
        else:
            assert identity["actor_ref"] == _SUBJECT_A
            assert scope["account_ref"] == _ACCOUNT_A
            assert scope["strategy_ref"] == _STRATEGY_A
            # The SDK registry records the deployment selector; the owner authority
            # maps it to the approved-target evidence scope (_EXPECTED_SCOPE) that
            # the application durable row stores.
            assert session["scope_ref"] == _APPROVED_TARGET_SELECTOR
            assert "orders.submit_approved_target" in session["write_operations"]


def _reg04_assert_owner_close_facts(
    closed: Any,
    *,
    expected_dispatches: tuple[tuple[str, bool, str], ...],
    expected_service_calls: Counter,
    group_fact: dict[str, Any],
) -> None:
    """One dispatch and one admission reservation per accepted operation."""

    assert isinstance(closed, tuple) and closed[0] == "closed", closed
    assert closed[1] == "closed"
    assert closed[2] == ()  # the plain unprotected submit port is never used
    assert closed[3] == expected_dispatches, closed[3]
    assert closed[4] == ()
    assert closed[5] == ()
    reserved = closed[6]
    assert len(reserved) == len(expected_dispatches)
    assert set(reserved) == {intent_id for intent_id, _, _ in expected_dispatches}
    assert len(set(reserved)) == len(reserved)  # no replay ever re-reserved
    assert closed[7] == group_fact
    assert Counter(closed[8]) == expected_service_calls, closed[8]
    assert closed[9] is False
    assert closed[10] is True
    assert all(not intent_id.startswith("group:") for intent_id in reserved)
    assert all(not intent_id.startswith("group:") for intent_id, _, _ in expected_dispatches)


def _reg04_assert_manual_rows(
    database_url: str, expected_key_intents: dict[str, str]
) -> None:
    manual_rows = _afi07._manual_order_operation_rows(database_url)
    assert len(manual_rows) == len(expected_key_intents), manual_rows
    by_digest = {row["operation_key_sha256"]: row for row in manual_rows}
    for key, intent_id in expected_key_intents.items():
        digest = hashlib.sha256(key.encode("ascii")).hexdigest()
        assert digest in by_digest, key
        row = by_digest[digest]
        assert row["owner_subject"] == _SUBJECT_B
        assert row["principal_ref"] == _APP_PRINCIPAL
        assert row["actor_ref"] == _SUBJECT_B
        assert row["delegate_ref"] == _DELEGATE_B
        assert row["scope_ref"] == _MANUAL_SUBMIT_SELECTOR
        assert row["account_ref"] == _ACCOUNT_A
        assert row["manual_book_ref"] == _MANUAL_BOOK_A
        assert row["last_record_state"] == "ACKED"
        assert row["intent_id"] == intent_id
    # One single manual book across every worker session/user name: no second
    # book is minted by a worker ID, JWT subject or session generation.
    assert {row["manual_book_ref"] for row in manual_rows} == {_MANUAL_BOOK_A}
    assert {row["account_ref"] for row in manual_rows} == {_ACCOUNT_A}
    assert len({row["intent_id"] for row in manual_rows}) == len(manual_rows)


def _reg04_assert_approved_row(
    database_url: str, *, operation_key: str, intent_id: str
) -> None:
    approved_rows = _afi07._approved_target_operation_rows(database_url)
    assert len(approved_rows) == 1, approved_rows
    row = approved_rows[0]
    assert row["owner_subject"] == _SUBJECT_A
    assert row["principal_ref"] == _APP_PRINCIPAL
    assert row["actor_ref"] == _SUBJECT_A
    assert row["delegate_ref"] == _DELEGATE_A
    assert row["operation_key_sha256"] == hashlib.sha256(
        operation_key.encode("ascii")
    ).hexdigest()
    assert row["intent_id"] == intent_id
    assert row["scope_ref"] == _APPROVED_TARGET_EXPECTED_SCOPE
    assert row["account_ref"] == _ACCOUNT_A
    assert row["strategy_ref"] == _STRATEGY_A


def _reg04_assert_journal(
    tmp_path: Any, expected: tuple[tuple[str, str, str], ...]
) -> None:
    from bt_api_execution import SqliteExecutionStore, group_leg_intent_id

    journal = SqliteExecutionStore(str(Path(tmp_path) / _OWNER_EXECUTION_FILE))
    try:
        for intent_id, strategy_id, provider_order_id in expected:
            record = journal.get(intent_id, scope=_afi07._afi07_execution_scope(strategy_id))
            assert record is not None, intent_id
            assert record.state.value == "ACKED", intent_id
            assert record.provider_order_id == provider_order_id, intent_id
        for leg_id in (
            _afi07._AFI07_GROUP_FIRST_LEG_ID,
            _afi07._AFI07_GROUP_HEDGE_LEG_ID,
        ):
            leg_intent_id = group_leg_intent_id(_afi07._AFI07_GROUP_ID, leg_id)
            assert (
                journal.get(leg_intent_id, scope=_afi07._afi07_execution_scope(_STRATEGY_B))
                is None
            ), leg_intent_id
    finally:
        journal.close()


def _run_reg04_dual_worker_one_owner(tmp_path: Any) -> None:
    """Node 1: two worker processes + manual book + one strategy run, one owner."""

    from pathlib import Path

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from bt_api_py.service_execution import ServiceExecutionClient
    from bt_api_py.service_runtime import ServiceRuntimeError

    context = multiprocessing.get_context("spawn")
    endpoint = _order._endpoint()
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{(Path(tmp_path) / _REG04_AUTHORITY_DB).as_posix()}",
        poolclass=NullPool,
    )
    keys = _reg04_owner_keys(engine)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    deployment_json = _reg04_deployment_json(endpoint, keys)
    registry_path = str(Path(tmp_path) / _OWNER_REGISTRY_FILE)

    token_a = _afi07._make_token(_SUBJECT_A, _JWT_SECRET)
    token_b = _afi07._make_token(_SUBJECT_B, _JWT_SECRET)

    host = None
    host_close_attempted = False
    producer = None
    servers: list[dict[str, Any]] = []
    all_servers: list[dict[str, Any]] = []
    primary_error: BaseException | None = None
    primary_traceback: Any = None
    cleanup_failures: list[BaseException] = []
    observed: dict[str, Any] = {}
    phase = "database_setup"
    _COMMAND_GUARD_STATE["active"] = True

    try:
        asyncio.run(_afi07._afi07_prepare_owner_database(engine, session_factory))

        phase = "owner_start"
        host = _afi07._afi07_start_owner_host(Path(tmp_path), context, keys, endpoint)
        baseline = _order._command(host, "group_facts")
        assert baseline[0] == "group_facts"
        assert baseline[1] == baseline[2]

        phase = "app_process_start"
        for label in (_APP_LABEL_1, _APP_LABEL_2):
            server = _reg04_start_app_server(
                context,
                database_url=keys["database_url"],
                deployment_json=deployment_json,
                label=label,
            )
            servers.append(server)
            all_servers.append(server)
        ports = {server["label"]: server["ready"][2] for server in servers}
        pids = [server["process"].pid for server in servers]
        assert len(set(pids)) == 2
        assert all(pid != os.getpid() for pid in pids)
        port1 = ports[_APP_LABEL_1]
        port2 = ports[_APP_LABEL_2]

        phase = "workers_before_strategy"
        asyncio.run(_reg04_dual_workers_before_strategy(port1, port2, token_a, token_b, observed))

        phase = "registry_before_strategy"
        registry_before = _reg04_registry_facts(registry_path)
        # Approved-target application writes carried strategy_ref A without
        # minting any strategy claim; only strategy-role sessions may claim.
        assert registry_before["claims"] == ()
        _reg04_assert_application_sessions(
            registry_before, expected_actor_counts={_SUBJECT_A: 2, _SUBJECT_B: 2}
        )

        phase = "strategy_run_start"
        producer = _reg04_strategy_runtime(endpoint, keys)
        strategy_client = ServiceExecutionClient(
            producer, "broker.orders", scope_ref=_afi07._AFI07_STRATEGY_SELECTOR
        )
        assert producer.start().degraded_count == 0

        phase = "registry_single_claim"
        registry_claim = _reg04_registry_facts(registry_path)
        claim = _reg04_assert_single_live_claim(registry_claim, expect_sessions=5)
        _reg04_assert_application_sessions(
            registry_claim, expected_actor_counts={_SUBJECT_A: 2, _SUBJECT_B: 2}
        )
        first_run_id = claim["run_id"]

        phase = "strategy_run_first_submit"
        first_strategy = _reg04_strategy_submit(strategy_client, _REG04_DUAL_STRATEGY_INTENT_1)
        assert first_strategy.state == "ACKED"

        phase = "worker_operation_under_claim"
        asyncio.run(
            _reg04_dual_worker_under_claim(port2, token_b, observed)
        )

        phase = "second_strategy_run_attempt"
        second_producer = _reg04_strategy_runtime(endpoint, keys)
        with pytest.raises(ServiceRuntimeError) as second_run_refusal:
            second_producer.start()
        assert second_run_refusal.value.code == "DUPLICATE_ACTIVE_RUN"
        _afi07._close_runtime(second_producer)
        observed["second_run_code"] = second_run_refusal.value.code

        phase = "registry_after_rejection"
        registry_after_refusal = _reg04_registry_facts(registry_path)
        # The rejected second run leaves no claim row, no ghost session and no
        # change to the first run's active claim.
        assert registry_after_refusal["claims"] == registry_claim["claims"]
        assert registry_after_refusal["sessions"] == registry_claim["sessions"]
        assert registry_after_refusal["live_sessions"] == 5

        phase = "worker_operation_after_rejection"
        asyncio.run(_reg04_dual_worker_after_rejection(port1, token_b, observed))

        phase = "strategy_run_second_submit"
        second_strategy = _reg04_strategy_submit(strategy_client, _REG04_DUAL_STRATEGY_INTENT_2)
        assert second_strategy.state == "ACKED"

        phase = "registry_final_live"
        registry_final = _reg04_registry_facts(registry_path)
        assert registry_final["claims"] == registry_claim["claims"]
        assert registry_final["sessions"] == registry_claim["sessions"]
        assert registry_final["live_sessions"] == 5

        phase = "strategy_run_close"
        _afi07._close_runtime(producer)
        producer = None
        registry_released = _reg04_registry_facts(registry_path)
        assert len(registry_released["claims"]) == 1
        assert registry_released["claims"][0]["run_id"] == first_run_id
        assert registry_released["claims"][0]["active_registration_id"] is None
        assert len(registry_released["sessions"]) == 4
        assert all(
            session["identity"]["role"] == _WireRole.APPLICATION_CLIENT.value
            for session in registry_released["sessions"]
        )

        phase = "app_process_close"
        cleanup_failures.extend(_reg04_stop_app_servers(servers, expected_workers=2))
        assert not cleanup_failures, tuple(type(error).__name__ for error in cleanup_failures)
        assert all(server["cleanup"]["exit_code"] == 0 for server in servers)
        assert all(server["cleanup"]["terminate_attempted"] is False for server in servers)
        servers = [
            server for server in servers if _afi07._manual_order_http_server_needs_cleanup(server)
        ]
        registry_all_gone = _reg04_registry_facts(registry_path)
        assert registry_all_gone["sessions"] == ()
        assert len(registry_all_gone["claims"]) == 1
        assert registry_all_gone["claims"][0]["active_registration_id"] is None

        phase = "group_facts_after_operations"
        group_after = _order._command(host, "group_facts")
        assert group_after[1] == group_after[2] == baseline[1]
        assert group_after[1]["event_types"] == ("GROUP_ACCEPTED",)
        assert group_after[1]["state"] == "PREPARING"
        assert group_after[1]["budget_state"] == "RESERVED"
        # One deduplicated reservation entry per account owner, not per leg.
        assert group_after[1]["reservation_phases"] == ("NOT_STARTED",)

        phase = "owner_close"
        host_close_attempted = True
        _afi07._close_default_deployment_service_host(host)
        closed = host.get("close_reply")
        assert isinstance(closed, tuple) and closed[0] == "closed", closed
        expected_dispatches = (
            (observed["manual_first"], True, "synthetic-approved-order-1"),
            (observed["manual_shared"], True, "synthetic-approved-order-2"),
            (observed["manual_second"], True, "synthetic-approved-order-3"),
            (observed["approved_intent"], True, "synthetic-approved-order-4"),
            (_REG04_DUAL_STRATEGY_INTENT_1, True, "synthetic-approved-order-5"),
            (observed["manual_under_claim"], True, "synthetic-approved-order-6"),
            (observed["manual_after_rejection"], True, "synthetic-approved-order-7"),
            (_REG04_DUAL_STRATEGY_INTENT_2, True, "synthetic-approved-order-8"),
        )
        expected_calls: Counter = Counter()
        # M1 + M1 replay + shared pair + M2-like + under-claim + after-rejection.
        expected_calls[
            (
                _APP_PRINCIPAL,
                _WireRole.APPLICATION_CLIENT.value,
                _SUBJECT_B,
                _DELEGATE_B,
                _ACCOUNT_A,
                "",
                _MANUAL_BOOK_A,
                "orders.submit",
            )
        ] = 7
        expected_calls[
            (
                _APP_PRINCIPAL,
                _WireRole.APPLICATION_CLIENT.value,
                _SUBJECT_A,
                _DELEGATE_A,
                _ACCOUNT_A,
                _STRATEGY_A,
                "",
                "orders.submit_approved_target",
            )
        ] = 2
        expected_calls[
            (
                _STRATEGY_B_PRINCIPAL,
                _WireRole.STRATEGY_CLIENT.value,
                _STRATEGY_B,
                "",
                _ACCOUNT_A,
                _STRATEGY_B,
                "",
                "orders.submit",
            )
        ] = 2
        _reg04_assert_owner_close_facts(
            closed,
            expected_dispatches=expected_dispatches,
            expected_service_calls=expected_calls,
            group_fact=baseline[1],
        )
        assert host["cleanup_facts"]["graceful_close"] == "succeeded"
        assert host["cleanup_facts"]["exit_code"] == 0

        phase = "durable_rows"
        _reg04_assert_manual_rows(
            keys["database_url"],
            {
                _REG04_DUAL_MANUAL_KEY_FIRST: observed["manual_first"],
                _REG04_DUAL_MANUAL_KEY_SHARED: observed["manual_shared"],
                _REG04_DUAL_MANUAL_KEY_SECOND: observed["manual_second"],
                _REG04_DUAL_MANUAL_KEY_UNDER_CLAIM: observed["manual_under_claim"],
                _REG04_DUAL_MANUAL_KEY_AFTER_REJECTION: observed["manual_after_rejection"],
            },
        )
        _reg04_assert_approved_row(
            keys["database_url"],
            operation_key=_REG04_DUAL_APPROVED_KEY,
            intent_id=observed["approved_intent"],
        )

        phase = "durable_journal"
        _reg04_assert_journal(
            tmp_path,
            (
                (observed["manual_first"], _MANUAL_BOOK_A, "synthetic-approved-order-1"),
                (observed["manual_shared"], _MANUAL_BOOK_A, "synthetic-approved-order-2"),
                (observed["manual_second"], _MANUAL_BOOK_A, "synthetic-approved-order-3"),
                (observed["approved_intent"], _STRATEGY_A, "synthetic-approved-order-4"),
                (_REG04_DUAL_STRATEGY_INTENT_1, _STRATEGY_B, "synthetic-approved-order-5"),
                (observed["manual_under_claim"], _MANUAL_BOOK_A, "synthetic-approved-order-6"),
                (
                    observed["manual_after_rejection"],
                    _MANUAL_BOOK_A,
                    "synthetic-approved-order-7",
                ),
                (_REG04_DUAL_STRATEGY_INTENT_2, _STRATEGY_B, "synthetic-approved-order-8"),
            ),
        )
    except BaseException as error:
        error.__dict__["reg04_failure_phase"] = phase
        error.add_note(f"reg04 dual-worker phase: {phase}")
        primary_error = error
        primary_traceback = error.__traceback__
    finally:
        if producer is not None:
            try:
                _afi07._close_runtime(producer)
            except BaseException as error:
                cleanup_failures.append(error)
        if servers:
            cleanup_failures.extend(_reg04_stop_app_servers(servers, expected_workers=2))
        if host is not None and not host_close_attempted:
            try:
                _afi07._close_default_deployment_service_host(host)
            except BaseException as error:
                cleanup_failures.append(error)
        try:
            asyncio.run(engine.dispose())
        except BaseException as error:
            cleanup_failures.append(error)
        _COMMAND_GUARD_STATE["active"] = False

    if primary_error is not None:
        if all_servers:
            child_cleanup_facts = _afi07._manual_order_http_cleanup_facts(all_servers)
            primary_error.__dict__["reg04_app_child_cleanup_facts"] = child_cleanup_facts
        host_cleanup_facts = host.get("cleanup_facts") if isinstance(host, dict) else None
        if isinstance(host_cleanup_facts, dict):
            primary_error.__dict__["reg04_owner_cleanup_facts"] = host_cleanup_facts
        if cleanup_failures:
            primary_error.__dict__["reg04_cleanup_failures"] = tuple(
                type(error).__name__ for error in cleanup_failures
            )
        raise primary_error.with_traceback(primary_traceback)
    if cleanup_failures:
        raise AssertionError(
            f"reg04 dual-worker cleanup had {len(cleanup_failures)} failure(s)"
        ) from cleanup_failures[0]


async def _reg04_dual_workers_before_strategy(
    port1: int, port2: int, token_a: str, token_b: str, observed: dict[str, Any]
) -> None:
    """Both workers operate; the same key fired at both processes is exactly-once."""

    first = await _reg04_manual_submit(
        port1, token=token_b, key=_REG04_DUAL_MANUAL_KEY_FIRST, label="manual-first"
    )
    replay = await _reg04_manual_submit(
        port1, token=token_b, key=_REG04_DUAL_MANUAL_KEY_FIRST, label="manual-first-replay"
    )
    assert replay["intent_id"] == first["intent_id"]
    assert replay["record"]["provider_order_id"] == first["record"]["provider_order_id"]
    observed["manual_first"] = first["intent_id"]

    shared, shared_peer = await _reg04_manual_concurrent_pair(
        port1, port2, token=token_b, key=_REG04_DUAL_MANUAL_KEY_SHARED
    )
    observed["manual_shared"] = shared["intent_id"]
    observed["manual_shared_order"] = shared["record"]["provider_order_id"]

    second = await _reg04_manual_submit(
        port2, token=token_b, key=_REG04_DUAL_MANUAL_KEY_SECOND, label="manual-second"
    )
    observed["manual_second"] = second["intent_id"]

    await _reg04_approved_submit_flow(
        publish_port=port1,
        create_port=port2,
        submit_port=port1,
        replay_port=port2,
        token=token_a,
        operation_key=_REG04_DUAL_APPROVED_KEY,
        observed=observed,
    )


async def _reg04_dual_worker_under_claim(
    port: int, token_b: str, observed: dict[str, Any]
) -> None:
    """A worker keeps operating while the strategy claim is held."""

    under_claim = await _reg04_manual_submit(
        port,
        token=token_b,
        key=_REG04_DUAL_MANUAL_KEY_UNDER_CLAIM,
        label="manual-under-claim",
    )
    observed["manual_under_claim"] = under_claim["intent_id"]


async def _reg04_dual_worker_after_rejection(
    port: int, token_b: str, observed: dict[str, Any]
) -> None:
    """A worker keeps operating after the second strategy run was rejected."""

    after = await _reg04_manual_submit(
        port,
        token=token_b,
        key=_REG04_DUAL_MANUAL_KEY_AFTER_REJECTION,
        label="manual-after-rejection",
    )
    observed["manual_after_rejection"] = after["intent_id"]


def test_reg04_dual_worker_processes_and_strategy_run_share_one_owner(
    tmp_path: Any,
) -> None:
    """Two AFI app processes, one manual book, one strategy run, one owner."""

    _run_reg04_dual_worker_one_owner(tmp_path)


def _run_reg04_late_worker_under_claim(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Node 2: a fresh app process registers and works under a live claim."""

    from pathlib import Path

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from bt_api_py.service_execution import ServiceExecutionClient
    from bt_api_py.service_runtime import ServiceRuntimeError

    context = multiprocessing.get_context("spawn")
    endpoint = _order._endpoint()
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{(Path(tmp_path) / _REG04_AUTHORITY_DB).as_posix()}",
        poolclass=NullPool,
    )
    keys = _reg04_owner_keys(engine)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    deployment_json = _reg04_deployment_json(endpoint, keys)
    registry_path = str(Path(tmp_path) / _OWNER_REGISTRY_FILE)

    token_a = _afi07._make_token(_SUBJECT_A, _JWT_SECRET)
    token_b = _afi07._make_token(_SUBJECT_B, _JWT_SECRET)

    host = None
    host_close_attempted = False
    producer = None
    servers: list[dict[str, Any]] = []
    all_servers: list[dict[str, Any]] = []
    primary_error: BaseException | None = None
    primary_traceback: Any = None
    cleanup_failures: list[BaseException] = []
    observed: dict[str, Any] = {}
    phase = "database_setup"
    _COMMAND_GUARD_STATE["active"] = True

    try:
        asyncio.run(_afi07._afi07_prepare_owner_database(engine, session_factory))

        phase = "owner_start"
        host = _afi07._afi07_start_owner_host(Path(tmp_path), context, keys, endpoint)
        baseline = _order._command(host, "group_facts")
        assert baseline[0] == "group_facts"
        assert baseline[1] == baseline[2]

        phase = "strategy_run_start"
        producer = _reg04_strategy_runtime(endpoint, keys)
        strategy_client = ServiceExecutionClient(
            producer, "broker.orders", scope_ref=_afi07._AFI07_STRATEGY_SELECTOR
        )
        assert producer.start().degraded_count == 0
        registry_claim_only = _reg04_registry_facts(registry_path)
        claim = _reg04_assert_single_live_claim(registry_claim_only, expect_sessions=1)

        phase = "strategy_run_first_submit"
        first_strategy = _reg04_strategy_submit(strategy_client, _REG04_LATE_STRATEGY_INTENT_1)
        assert first_strategy.state == "ACKED"

        phase = "late_app_process_start"
        server = _reg04_start_app_server(
            context,
            database_url=keys["database_url"],
            deployment_json=deployment_json,
            label=_APP_LABEL_1,
        )
        servers.append(server)
        all_servers.append(server)
        port = server["ready"][2]
        assert server["process"].pid != os.getpid()

        phase = "registry_workers_under_claim"
        registry_under_claim = _reg04_registry_facts(registry_path)
        # The two worker registrations underneath the live claim: no new claim,
        # no sixth session, the original claim untouched.
        assert registry_under_claim["claims"] == registry_claim_only["claims"]
        assert len(registry_under_claim["sessions"]) == 3
        assert registry_under_claim["live_sessions"] == 3
        _reg04_assert_application_sessions(
            registry_under_claim, expected_actor_counts={_SUBJECT_A: 1, _SUBJECT_B: 1}
        )
        holders = [
            session
            for session in registry_under_claim["sessions"]
            if session["registration_id"] == claim["active_registration_id"]
        ]
        assert len(holders) == 1
        assert holders[0]["identity"]["role"] == _WireRole.STRATEGY_CLIENT.value

        phase = "worker_operations_under_claim"
        first = asyncio.run(_run_reg04_late_worker_operations(port, token_a, token_b, observed))

        phase = "second_strategy_run_attempt"
        second_producer = _reg04_strategy_runtime(endpoint, keys)
        with pytest.raises(ServiceRuntimeError) as second_run_refusal:
            second_producer.start()
        assert second_run_refusal.value.code == "DUPLICATE_ACTIVE_RUN"
        _afi07._close_runtime(second_producer)
        observed["second_run_code"] = second_run_refusal.value.code
        registry_after_rejection = _reg04_registry_facts(registry_path)
        assert registry_after_rejection["claims"] == registry_claim_only["claims"]
        assert registry_after_rejection["sessions"] == registry_under_claim["sessions"]

        phase = "worker_replay_after_rejection"
        replay = asyncio.run(
            _reg04_manual_submit(
                port,
                token=token_b,
                key=_REG04_LATE_MANUAL_KEY,
                label="late-manual-replay-after-rejection",
            )
        )
        assert replay["intent_id"] == first["intent_id"]
        assert replay["record"]["provider_order_id"] == first["record"]["provider_order_id"]

        phase = "strategy_run_second_submit"
        second_strategy = _reg04_strategy_submit(strategy_client, _REG04_LATE_STRATEGY_INTENT_2)
        assert second_strategy.state == "ACKED"

        phase = "strategy_run_close"
        _afi07._close_runtime(producer)
        producer = None
        registry_released = _reg04_registry_facts(registry_path)
        assert len(registry_released["claims"]) == 1
        assert registry_released["claims"][0]["run_id"] == claim["run_id"]
        assert registry_released["claims"][0]["active_registration_id"] is None
        assert len(registry_released["sessions"]) == 2

        phase = "app_process_close"
        cleanup_failures.extend(_reg04_stop_app_servers(servers, expected_workers=2))
        assert not cleanup_failures, tuple(type(error).__name__ for error in cleanup_failures)
        assert all(server["cleanup"]["exit_code"] == 0 for server in servers)
        assert all(server["cleanup"]["terminate_attempted"] is False for server in servers)
        servers = [
            server for server in servers if _afi07._manual_order_http_server_needs_cleanup(server)
        ]
        registry_all_gone = _reg04_registry_facts(registry_path)
        assert registry_all_gone["sessions"] == ()
        assert len(registry_all_gone["claims"]) == 1
        assert registry_all_gone["claims"][0]["active_registration_id"] is None

        phase = "group_facts_after_operations"
        group_after = _order._command(host, "group_facts")
        assert group_after[1] == group_after[2] == baseline[1]
        assert group_after[1]["event_types"] == ("GROUP_ACCEPTED",)
        assert group_after[1]["state"] == "PREPARING"
        assert group_after[1]["budget_state"] == "RESERVED"
        assert group_after[1]["reservation_phases"] == ("NOT_STARTED",)

        phase = "owner_close"
        host_close_attempted = True
        _afi07._close_default_deployment_service_host(host)
        closed = host.get("close_reply")
        assert isinstance(closed, tuple) and closed[0] == "closed", closed
        expected_dispatches = (
            (_REG04_LATE_STRATEGY_INTENT_1, True, "synthetic-approved-order-1"),
            (observed["late_manual"], True, "synthetic-approved-order-2"),
            (observed["approved_intent"], True, "synthetic-approved-order-3"),
            (_REG04_LATE_STRATEGY_INTENT_2, True, "synthetic-approved-order-4"),
        )
        expected_calls: Counter = Counter()
        expected_calls[
            (
                _APP_PRINCIPAL,
                _WireRole.APPLICATION_CLIENT.value,
                _SUBJECT_B,
                _DELEGATE_B,
                _ACCOUNT_A,
                "",
                _MANUAL_BOOK_A,
                "orders.submit",
            )
        ] = 2
        expected_calls[
            (
                _APP_PRINCIPAL,
                _WireRole.APPLICATION_CLIENT.value,
                _SUBJECT_A,
                _DELEGATE_A,
                _ACCOUNT_A,
                _STRATEGY_A,
                "",
                "orders.submit_approved_target",
            )
        ] = 2
        expected_calls[
            (
                _STRATEGY_B_PRINCIPAL,
                _WireRole.STRATEGY_CLIENT.value,
                _STRATEGY_B,
                "",
                _ACCOUNT_A,
                _STRATEGY_B,
                "",
                "orders.submit",
            )
        ] = 2
        _reg04_assert_owner_close_facts(
            closed,
            expected_dispatches=expected_dispatches,
            expected_service_calls=expected_calls,
            group_fact=baseline[1],
        )
        assert host["cleanup_facts"]["graceful_close"] == "succeeded"
        assert host["cleanup_facts"]["exit_code"] == 0

        phase = "durable_rows"
        _reg04_assert_manual_rows(
            keys["database_url"], {_REG04_LATE_MANUAL_KEY: observed["late_manual"]}
        )
        _reg04_assert_approved_row(
            keys["database_url"],
            operation_key=_REG04_LATE_APPROVED_KEY,
            intent_id=observed["approved_intent"],
        )

        phase = "durable_journal"
        _reg04_assert_journal(
            tmp_path,
            (
                (_REG04_LATE_STRATEGY_INTENT_1, _STRATEGY_B, "synthetic-approved-order-1"),
                (observed["late_manual"], _MANUAL_BOOK_A, "synthetic-approved-order-2"),
                (observed["approved_intent"], _STRATEGY_A, "synthetic-approved-order-3"),
                (_REG04_LATE_STRATEGY_INTENT_2, _STRATEGY_B, "synthetic-approved-order-4"),
            ),
        )
    except BaseException as error:
        error.__dict__["reg04_failure_phase"] = phase
        error.add_note(f"reg04 late-worker phase: {phase}")
        primary_error = error
        primary_traceback = error.__traceback__
    finally:
        if producer is not None:
            try:
                _afi07._close_runtime(producer)
            except BaseException as error:
                cleanup_failures.append(error)
        if servers:
            cleanup_failures.extend(_reg04_stop_app_servers(servers, expected_workers=2))
        if host is not None and not host_close_attempted:
            try:
                _afi07._close_default_deployment_service_host(host)
            except BaseException as error:
                cleanup_failures.append(error)
        try:
            asyncio.run(engine.dispose())
        except BaseException as error:
            cleanup_failures.append(error)
        _COMMAND_GUARD_STATE["active"] = False

    if primary_error is not None:
        if all_servers:
            child_cleanup_facts = _afi07._manual_order_http_cleanup_facts(all_servers)
            primary_error.__dict__["reg04_app_child_cleanup_facts"] = child_cleanup_facts
        host_cleanup_facts = host.get("cleanup_facts") if isinstance(host, dict) else None
        if isinstance(host_cleanup_facts, dict):
            primary_error.__dict__["reg04_owner_cleanup_facts"] = host_cleanup_facts
        if cleanup_failures:
            primary_error.__dict__["reg04_cleanup_failures"] = tuple(
                type(error).__name__ for error in cleanup_failures
            )
        raise primary_error.with_traceback(primary_traceback)
    if cleanup_failures:
        raise AssertionError(
            f"reg04 late-worker cleanup had {len(cleanup_failures)} failure(s)"
        ) from cleanup_failures[0]


async def _run_reg04_late_worker_operations(
    port: int, token_a: str, token_b: str, observed: dict[str, Any]
) -> dict[str, Any]:
    """Manual and approved-target operations from the late worker under claim."""

    first = await _reg04_manual_submit(
        port, token=token_b, key=_REG04_LATE_MANUAL_KEY, label="late-manual"
    )
    observed["late_manual"] = first["intent_id"]
    await _reg04_approved_submit_flow(
        publish_port=port,
        create_port=port,
        submit_port=port,
        replay_port=port,
        token=token_a,
        operation_key=_REG04_LATE_APPROVED_KEY,
        observed=observed,
    )
    return first


def test_reg04_worker_registration_under_live_strategy_claim_keeps_single_active_run(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fresh app process registers and works while the strategy claim is held."""

    _run_reg04_late_worker_under_claim(tmp_path, monkeypatch)
