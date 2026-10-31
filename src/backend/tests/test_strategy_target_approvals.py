"""Focused persistence and authority-state tests for approved targets."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import os
import re
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from pydantic_settings import BaseSettings as _BaseSettings
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

_SYNTHETIC_ENV = {
    "DEBUG": "false",
    "DATABASE_URL": "sqlite+aiosqlite://",
    "SECRET_KEY": "approved-target-test-secret-0123456789",
    "ADMIN_PASSWORD": "ApprovedTargetSyntheticAdmin!98765",
    "JWT_SECRET_KEY": "approved-target-test-jwt-secret-0123456789",
    "JWT_ALGORITHM": "HS256",
    "LOG_LEVEL": "CRITICAL",
    "LOG_DIR": tempfile.mkdtemp(prefix="afi_approved_target_unit_"),
    "BT_API_LOG_DIR": tempfile.mkdtemp(prefix="afi_approved_target_sdk_"),
    "SQL_ECHO": "false",
    "AI_CHAT_ENABLED": "false",
    "AI_CHAT_BASE_URL": "",
    "AI_CHAT_API_KEY": "",
    "AI_CHAT_MODEL": "",
}
_ORIGINAL_ENV = os.environ
_ORIGINAL_SETTINGS_INIT = _BaseSettings.__init__
_OPERATION_KEY = "http-key-a"


def _settings_without_dotenv(self, *args, **kwargs):
    kwargs["_env_file"] = None
    _ORIGINAL_SETTINGS_INIT(self, *args, **kwargs)


_BaseSettings.__init__ = _settings_without_dotenv
os.environ = dict(_SYNTHETIC_ENV)  # noqa: B003 - isolate settings from ambient/private values
try:
    import app.models  # noqa: F401,E402
    from app.db.database import Base, async_session_maker, engine  # noqa: E402
    from app.models.strategy_approval_authority import (  # noqa: E402
        StrategyApprovalAuthorityEpoch,
    )
    from app.models.strategy_target_approval import (  # noqa: E402
        StrategyTargetApproval,
        StrategyTargetApprovalEvent,
    )
    from app.services.strategy_target_approvals import (  # noqa: E402
        ApprovedTargetCurrentStateV1,
        StrategyTargetApprovalError,
        canonical_target_json,
        canonical_target_sha256,
        consume_approved_target_v1,
        create_approved_order_target,
        reserve_approved_target_operation,
        resolve_approved_target_v1,
        revoke_approved_order_target,
    )
finally:
    _BaseSettings.__init__ = _ORIGINAL_SETTINGS_INIT
    os.environ = _ORIGINAL_ENV  # noqa: B003 - restore process environment


@pytest_asyncio.fixture(autouse=True)
async def _isolated_approval_schema():
    tables = [
        StrategyApprovalAuthorityEpoch.__table__,
        StrategyTargetApproval.__table__,
        StrategyTargetApprovalEvent.__table__,
    ]
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=tables))
    yield
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync: Base.metadata.drop_all(sync, tables=tables))
    await engine.dispose()


def _identity(**changes):
    values = {
        "role": "application_client",
        "principal_ref": "principal-a",
        "actor_ref": "actor-a",
        "delegate_ref": "delegate-a",
    }
    values.update(changes)
    return SimpleNamespace(**values)


def _wire_scope(**changes):
    values = {
        "execution_domain_ref": "paper:synthetic",
        "account_ref": "account-a",
        "account_refs": (),
        "strategy_ref": "strategy-a",
        "run_id": None,
        "manual_book_ref": None,
        "portfolio_ref": None,
        "group_id": None,
        "leg_id": None,
    }
    values.update(changes)
    return SimpleNamespace(**values)


def _target(**changes):
    value = {
        "schema_id": "bt_api.approved_order_target",
        "schema_version": 1,
        "target_ref": "target-a",
        "target_version": 1,
        "owner_subject": "subject-a",
        "principal_ref": "principal-a",
        "actor_ref": "actor-a",
        "delegate_ref": "delegate-a",
        "scope_ref": "strategy-scope-a-v1",
        "wire_scope": {
            "execution_domain_ref": "paper:synthetic",
            "account_ref": "account-a",
            "account_refs": [],
            "strategy_ref": "strategy-a",
            "run_id": None,
            "manual_book_ref": None,
            "portfolio_ref": None,
            "group_id": None,
            "leg_id": None,
        },
        "strategy_version": 7,
        "membership_version": None,
        "membership_sha256": None,
        "instrument": "BTC-USDT",
        "metadata_version": "instrument-v1",
        "side": "BUY",
        "position_effect": "OPEN",
        "order_type": "LIMIT",
        "quantity": "1.25",
        "price": "100.5",
        "time_in_force": "GTC",
        "reduce_only": False,
        "deadline_ns": None,
        "limits": {
            "max_quantity": "2",
            "max_notional": "200",
            "min_price": "1",
            "max_price": "200",
        },
        "policy_ref": "policy-a",
        "policy_version": 3,
        "policy_sha256": "a" * 64,
    }
    value.update(changes)
    return value


async def _create_approval(db, *, target=None, approval_ref="approval-a"):
    target_value = _target() if target is None else target
    return await create_approved_order_target(
        db,
        target=target_value,
        target_sha256=canonical_target_sha256(target_value),
        approval_ref=approval_ref,
        approval_version=1,
        owner_subject="subject-a",
        expected_scope_ref="strategy-scope-a-v1",
        target_identity=_identity(),
        target_wire_scope=_wire_scope(),
        approved_by_subject="approver-a",
        approved_by_principal_ref="approval-principal",
        approved_by_actor_ref="approval-console",
        approved_by_delegate_ref=None,
        approved_at_ns=100,
        expires_at_ns=1_000,
        strategy_version_source_id="version-source-a",
        strategy_version_branch="main",
        strategy_version_sha256="c" * 64,
    )


async def _reserve(db, approval, *, operation_key=_OPERATION_KEY, **overrides):
    values = {
        "approval_ref": approval.approval_ref,
        "approval_version": approval.approval_version,
        "target_sha256": approval.target_sha256,
        "operation_key": operation_key,
        "intent_id": f"intent-{approval.approval_ref}",
        "owner_subject": "subject-a",
        "principal_ref": "principal-a",
        "expected_scope_ref": "strategy-scope-a-v1",
        "identity": _identity(),
        "wire_scope": _wire_scope(),
        "now_ns": 200,
    }
    values.update(overrides)
    return await reserve_approved_target_operation(db, **values)


class _SyntheticCurrentStateProvider:
    def __init__(self, **changes):
        self.changes = changes
        self.calls = 0
        self.same_transaction = False

    async def read_current_approval_state_v1(
        self,
        db,
        approval_ref,
        approval_version,
        target_sha256,
        *,
        owner_subject,
        principal_ref,
        expected_scope_ref,
        identity,
        wire_scope,
    ):
        self.calls += 1
        self.same_transaction = db.in_transaction()
        values = {
            "target_ref": "target-a",
            "target_version": 1,
            "strategy_version": 7,
            "strategy_version_source_id": "version-source-a",
            "strategy_version_branch": "main",
            "strategy_version_sha256": "c" * 64,
            "membership_version": None,
            "membership_sha256": None,
            "policy_ref": "policy-a",
            "policy_version": 3,
            "policy_sha256": "a" * 64,
        }
        values.update(self.changes)
        return ApprovedTargetCurrentStateV1(**values)


def test_target_v1_has_canonical_json_digest_and_rejects_unsupported_terms():
    target = _target()
    canonical = canonical_target_json(target)
    assert canonical == json.dumps(
        target, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )
    assert canonical_target_sha256(target) == hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    assert "signal_id" not in json.loads(canonical)
    assert "tags" not in json.loads(canonical)

    for mutation in (
        lambda item: item.update(signal_id="client-controlled"),
        lambda item: item.update(tags={"approved": True}),
        lambda item: item.update(quantity=1.25),
        lambda item: item.update(position_effect="CLOSE", reduce_only=False),
        lambda item: item.update(wire_scope={**item["wire_scope"], "group_id": "group-a"}),
        lambda item: item.update(limits={**item["limits"], "max_quantity": None}),
    ):
        invalid = _target()
        mutation(invalid)
        with pytest.raises(StrategyTargetApprovalError) as error:
            canonical_target_json(invalid)
        assert error.value.code == "APPROVAL_TARGET_INVALID"
        assert error.value.ambiguous is False


def test_migration_is_idempotent_and_checks_primary_keys_and_foreign_key():
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "20261016_strategy_target_approvals.py"
    )
    spec = importlib.util.spec_from_file_location("strategy_target_approval_revision", migration_path)
    assert spec is not None and spec.loader is not None
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)

    sync_engine = sa.create_engine("sqlite://")
    try:
        with sync_engine.begin() as connection:
            context = MigrationContext.configure(connection)
            with Operations.context(context):
                revision.upgrade()
                revision.upgrade()
            inspector = sa.inspect(connection)
            assert inspector.get_pk_constraint("strategy_target_approvals")[
                "constrained_columns"
            ] == ["approval_ref"]
            assert inspector.get_pk_constraint("strategy_target_approval_events")[
                "constrained_columns"
            ] == ["id"]
            assert any(
                foreign_key["constrained_columns"] == ["approval_ref"]
                and foreign_key["referred_table"] == "strategy_target_approvals"
                and foreign_key["referred_columns"] == ["approval_ref"]
                for foreign_key in inspector.get_foreign_keys("strategy_target_approval_events")
            )
    finally:
        sync_engine.dispose()


@pytest.mark.parametrize(
    ("table_name", "nullable_column", "ondelete", "should_reject"),
    [
        ("strategy_target_approvals", "owner_subject", None, True),
        ("strategy_target_approval_events", "actor_subject", None, True),
        ("strategy_target_approval_events", None, "CASCADE", True),
        ("strategy_target_approval_events", None, "NO ACTION", False),
    ],
)
def test_migration_rejects_nullable_text_or_cascading_and_accepts_no_action(
    table_name, nullable_column, ondelete, should_reject
):
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "20261016_strategy_target_approvals.py"
    )
    spec = importlib.util.spec_from_file_location("strategy_target_approval_revision", migration_path)
    assert spec is not None and spec.loader is not None
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)

    sync_engine = sa.create_engine("sqlite://")
    try:
        with sync_engine.begin() as connection:
            context = MigrationContext.configure(connection)
            with Operations.context(context):
                revision.upgrade()

        with sync_engine.begin() as connection:
            table_sql = connection.exec_driver_sql(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table_name,),
            ).scalar_one()
            if nullable_column is not None:
                lengths = (
                    revision._APPROVAL_LENGTHS
                    if table_name == "strategy_target_approvals"
                    else revision._EVENT_LENGTHS
                )
                pattern = (
                    rf"(?<![A-Za-z0-9_]){re.escape(nullable_column)}\s+"
                    rf"VARCHAR\({lengths[nullable_column]}\)\s+NOT NULL"
                )
                incompatible_sql, replacements = re.subn(
                    pattern,
                    f"{nullable_column} VARCHAR({lengths[nullable_column]})",
                    table_sql,
                    count=1,
                    flags=re.IGNORECASE,
                )
                assert replacements == 1
            else:
                incompatible_sql, replacements = re.subn(
                    r"ON DELETE RESTRICT",
                    f"ON DELETE {ondelete}",
                    table_sql,
                    count=1,
                    flags=re.IGNORECASE,
                )
                assert replacements == 1
            index_sql = connection.exec_driver_sql(
                "SELECT sql FROM sqlite_master "
                "WHERE type = 'index' AND tbl_name = ? AND sql IS NOT NULL ORDER BY name",
                (table_name,),
            ).scalars().all()

            # Rebuild only the candidate existing table with one incompatible
            # property; all its other columns, constraints and indexes stay as
            # produced by the real migration.
            if table_name == "strategy_target_approvals":
                connection.exec_driver_sql('DROP TABLE "strategy_target_approval_events"')
            connection.exec_driver_sql(f'DROP TABLE "{table_name}"')
            connection.exec_driver_sql(incompatible_sql)
            for statement in index_sql:
                connection.exec_driver_sql(statement)

        with sync_engine.begin() as connection:
            context = MigrationContext.configure(connection)
            with Operations.context(context):
                if should_reject:
                    with pytest.raises(
                        RuntimeError,
                        match="STRATEGY_TARGET_APPROVAL_SCHEMA_CONFLICT",
                    ):
                        revision.upgrade()
                else:
                    revision.upgrade()
    finally:
        sync_engine.dispose()


@pytest.mark.asyncio
async def test_competing_file_sqlite_sessions_reserve_one_intent_and_refresh_loser(tmp_path):
    database_path = tmp_path / "approved-target-reservation-race.sqlite3"
    race_engine = create_async_engine(
        sa.engine.URL.create("sqlite+aiosqlite", database=str(database_path)),
        connect_args={"timeout": 10},
    )
    race_sessions = async_sessionmaker(race_engine, expire_on_commit=False)
    tables = [
        StrategyApprovalAuthorityEpoch.__table__,
        StrategyTargetApprovalEvent.__table__,
        StrategyTargetApproval.__table__,
    ]
    try:
        async with race_engine.begin() as connection:
            await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=tables))
        async with race_sessions() as db:
            approval = await _create_approval(db)
            approval_identity = SimpleNamespace(
                approval_ref=approval.approval_ref,
                approval_version=approval.approval_version,
                target_sha256=approval.target_sha256,
            )

        start = asyncio.Barrier(2)

        async def contender(intent_id: str):
            async with race_sessions() as db:
                await start.wait()
                try:
                    claim = await _reserve(
                        db,
                        approval_identity,
                        operation_key="same-operation-key",
                        intent_id=intent_id,
                    )
                    return ("reserved", intent_id, claim)
                except StrategyTargetApprovalError as error:
                    return ("rejected", intent_id, error.code, error.ambiguous)

        outcomes = await asyncio.wait_for(
            asyncio.gather(contender("intent-race-a"), contender("intent-race-b")),
            timeout=15,
        )
        winners = [item for item in outcomes if item[0] == "reserved"]
        losers = [item for item in outcomes if item[0] == "rejected"]
        assert len(winners) == len(losers) == 1
        assert winners[0][2].created is True
        assert losers[0][2:] == ("APPROVAL_OPERATION_CONFLICT", False)

        async with race_sessions() as db:
            stored = await db.get(StrategyTargetApproval, approval_identity.approval_ref)
            events = (
                await db.execute(
                    select(StrategyTargetApprovalEvent).where(
                        StrategyTargetApprovalEvent.approval_ref
                        == approval_identity.approval_ref
                    )
                )
            ).scalars().all()
        assert stored is not None
        assert stored.intent_id == winners[0][1]
        assert stored.record_version == 2
        assert [event.event_type for event in events].count("OPERATION_RESERVED") == 1
    finally:
        await race_engine.dispose()


@pytest.mark.asyncio
async def test_create_resolve_and_identity_scope_owner_checks_are_exact():
    async with async_session_maker() as db:
        row = await _create_approval(db)
        assert row.state == "APPROVED"
        assert row.approval_version == 1
        assert row.record_version == 1

        # Resolve is available only after the operation has atomically pinned
        # its stable Execution intent identifier.
        claim = await _reserve(db, row)
        resolved = await resolve_approved_target_v1(
            db,
            row.approval_ref,
            row.approval_version,
            row.target_sha256,
            operation_key=_OPERATION_KEY,
            intent_id=claim.intent_id,
            owner_subject="subject-a",
            principal_ref="principal-a",
            expected_scope_ref="strategy-scope-a-v1",
            identity=_identity(),
            wire_scope=_wire_scope(),
        )
        assert resolved == _target()
        with pytest.raises(StrategyTargetApprovalError) as operation_conflict:
            await resolve_approved_target_v1(
                db,
                row.approval_ref,
                row.approval_version,
                row.target_sha256,
                operation_key="different-service-operation",
                intent_id=claim.intent_id,
                owner_subject="subject-a",
                principal_ref="principal-a",
                expected_scope_ref="strategy-scope-a-v1",
                identity=_identity(),
                wire_scope=_wire_scope(),
            )
        assert operation_conflict.value.code == "APPROVAL_OPERATION_CONFLICT"

        denied_calls = (
            {
                "owner_subject": "subject-b",
                "principal_ref": "principal-a",
                "expected_scope_ref": "strategy-scope-a-v1",
                "identity": _identity(),
                "wire_scope": _wire_scope(),
                "code": "APPROVAL_OWNER_BINDING_MISMATCH",
            },
            {
                "owner_subject": "subject-a",
                "principal_ref": "principal-a",
                "expected_scope_ref": "strategy-scope-a-v1",
                "identity": _identity(actor_ref="actor-b"),
                "wire_scope": _wire_scope(),
                "code": "APPROVAL_IDENTITY_MISMATCH",
            },
            {
                "owner_subject": "subject-a",
                "principal_ref": "principal-a",
                "expected_scope_ref": "strategy-scope-a-v1",
                "identity": _identity(),
                "wire_scope": _wire_scope(account_ref="account-b"),
                "code": "APPROVAL_SCOPE_MISMATCH",
            },
            {
                "owner_subject": "subject-a",
                "principal_ref": "principal-a",
                "expected_scope_ref": "other-scope",
                "identity": _identity(),
                "wire_scope": _wire_scope(),
                "code": "APPROVAL_SCOPE_MISMATCH",
            },
        )
        for call in denied_calls:
            code = call.pop("code")
            with pytest.raises(StrategyTargetApprovalError) as error:
                await resolve_approved_target_v1(
                    db,
                    row.approval_ref,
                    row.approval_version,
                    row.target_sha256,
                    operation_key=_OPERATION_KEY,
                    intent_id=claim.intent_id,
                    **call,
                )
            assert error.value.code == code


@pytest.mark.asyncio
async def test_operation_reservation_reuses_intent_and_rejects_conflicting_key():
    async with async_session_maker() as db:
        row = await _create_approval(db)
        first = await _reserve(db, row)
        replay = await _reserve(db, row)
        assert first.created is True
        assert replay.created is False
        assert replay.intent_id == first.intent_id
        assert replay.operation_request_sha256 == first.operation_request_sha256
        assert replay.record_version == first.record_version == 2

        with pytest.raises(StrategyTargetApprovalError) as conflict:
            await _reserve(db, row, operation_key="different-http-key")
        assert conflict.value.code == "APPROVAL_OPERATION_CONFLICT"

        with pytest.raises(StrategyTargetApprovalError) as intent_conflict:
            await _reserve(db, row, intent_id="intent-not-the-reservation")
        assert intent_conflict.value.code == "APPROVAL_OPERATION_CONFLICT"

        persisted = await db.get(StrategyTargetApproval, row.approval_ref)
        assert persisted is not None
        assert persisted.intent_id == first.intent_id
        events = (
            await db.execute(
                select(StrategyTargetApprovalEvent)
                .where(StrategyTargetApprovalEvent.approval_ref == row.approval_ref)
                .order_by(StrategyTargetApprovalEvent.record_version)
            )
        ).scalars().all()
        assert [(event.event_type, event.record_version) for event in events] == [
            ("APPROVED", 1),
            ("OPERATION_RESERVED", 2),
        ]


@pytest.mark.asyncio
async def test_one_idempotency_key_cannot_be_reserved_for_two_approvals():
    async with async_session_maker() as db:
        first_approval = await _create_approval(db)
        second_target = _target(target_ref="target-b")
        second_approval = await _create_approval(
            db, target=second_target, approval_ref="approval-b"
        )
        second_approval_ref = second_approval.approval_ref
        first = await _reserve(db, first_approval)
        with pytest.raises(StrategyTargetApprovalError) as conflict:
            await _reserve(db, second_approval)
        assert conflict.value.code == "APPROVAL_OPERATION_CONFLICT"
        persisted = await db.get(StrategyTargetApproval, second_approval_ref)
        assert persisted is not None
        assert persisted.intent_id is None
        assert first.intent_id != persisted.intent_id


@pytest.mark.asyncio
async def test_consume_is_separate_receipt_and_exact_replay_never_changes_receipt():
    async with async_session_maker() as db:
        row = await _create_approval(db)
        approval_ref = row.approval_ref
        approval_version = row.approval_version
        target_sha256 = row.target_sha256
        claim = await _reserve(db, row)
        provider = _SyntheticCurrentStateProvider()
        with pytest.raises(StrategyTargetApprovalError) as operation_conflict:
            await consume_approved_target_v1(
                db,
                approval_ref,
                approval_version,
                target_sha256,
                operation_key="different-service-operation",
                intent_id=claim.intent_id,
                intent_sha256="b" * 64,
                owner_subject="subject-a",
                principal_ref="principal-a",
                expected_scope_ref="strategy-scope-a-v1",
                identity=_identity(),
                wire_scope=_wire_scope(),
                current_state_provider=provider,
                now_ns=399,
            )
        assert operation_conflict.value.code == "APPROVAL_OPERATION_CONFLICT"
        assert provider.calls == 0

        receipt = await consume_approved_target_v1(
            db,
            approval_ref,
            approval_version,
            target_sha256,
            operation_key=_OPERATION_KEY,
            intent_id=claim.intent_id,
            intent_sha256="b" * 64,
            owner_subject="subject-a",
            principal_ref="principal-a",
            expected_scope_ref="strategy-scope-a-v1",
            identity=_identity(),
            wire_scope=_wire_scope(),
            current_state_provider=provider,
            now_ns=400,
        )
        assert receipt["disposition"] == "CONSUMED_NEW"
        assert receipt["intent_id"] == claim.intent_id
        assert receipt["intent_sha256"] == "b" * 64
        assert receipt["consumed_record_version"] == 3
        assert provider.same_transaction is True

        replay = await consume_approved_target_v1(
            db,
            approval_ref,
            approval_version,
            target_sha256,
            operation_key=_OPERATION_KEY,
            intent_id=claim.intent_id,
            intent_sha256="b" * 64,
            owner_subject="subject-a",
            principal_ref="principal-a",
            expected_scope_ref="strategy-scope-a-v1",
            identity=_identity(),
            wire_scope=_wire_scope(),
            current_state_provider=provider,
            now_ns=2_000,
        )
        assert replay["disposition"] == "ALREADY_CONSUMED"
        assert provider.calls == 1
        assert {key: value for key, value in replay.items() if key != "disposition"} == {
            key: value for key, value in receipt.items() if key != "disposition"
        }

        with pytest.raises(StrategyTargetApprovalError) as conflict:
            await consume_approved_target_v1(
                db,
                approval_ref,
                approval_version,
                target_sha256,
                operation_key=_OPERATION_KEY,
                intent_id=claim.intent_id,
                intent_sha256="c" * 64,
                owner_subject="subject-a",
                principal_ref="principal-a",
                expected_scope_ref="strategy-scope-a-v1",
                identity=_identity(),
                wire_scope=_wire_scope(),
                current_state_provider=provider,
                now_ns=2_001,
            )
        assert conflict.value.code == "APPROVAL_CONSUMED_CONFLICT"
        with pytest.raises(StrategyTargetApprovalError) as revoke_conflict:
            await revoke_approved_order_target(
                db,
                approval_ref=approval_ref,
                approval_version=approval_version,
                owner_subject="subject-a",
                revoker_subject="approver-a",
                revoker_principal_ref="approval-principal",
                revoker_actor_ref="approval-console",
                revoker_delegate_ref=None,
                reason_code="policy_withdrawn",
                revoked_at_ns=500,
            )
        assert revoke_conflict.value.code == "APPROVAL_CONSUMED_CONFLICT"

        events = (
            await db.execute(
                select(StrategyTargetApprovalEvent)
                .where(StrategyTargetApprovalEvent.approval_ref == approval_ref)
                .order_by(StrategyTargetApprovalEvent.record_version)
            )
        ).scalars().all()
        assert [(event.event_type, event.record_version) for event in events] == [
            ("APPROVED", 1),
            ("OPERATION_RESERVED", 2),
            ("CONSUMED", 3),
        ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stale_values",
    (
        {"target_version": 2},
        {"strategy_version": 8},
        {"membership_version": 4, "membership_sha256": "b" * 64},
        {"policy_version": 4},
        {"policy_sha256": "b" * 64},
    ),
)
async def test_consume_fails_closed_when_trusted_current_versions_are_missing_or_stale(
    stale_values,
):
    async with async_session_maker() as db:
        row = await _create_approval(db)
        approval_ref = row.approval_ref
        approval_version = row.approval_version
        target_sha256 = row.target_sha256
        claim = await _reserve(db, row)
        provider = _SyntheticCurrentStateProvider(**stale_values)
        with pytest.raises(StrategyTargetApprovalError) as error:
            await consume_approved_target_v1(
                db,
                approval_ref,
                approval_version,
                target_sha256,
                operation_key=_OPERATION_KEY,
                intent_id=claim.intent_id,
                intent_sha256="f" * 64,
                owner_subject="subject-a",
                principal_ref="principal-a",
                expected_scope_ref="strategy-scope-a-v1",
                identity=_identity(),
                wire_scope=_wire_scope(),
                current_state_provider=provider,
                now_ns=400,
            )
        assert error.value.code == "APPROVAL_POLICY_STALE"
        assert error.value.ambiguous is False
        assert provider.calls == 1
        assert provider.same_transaction is True
        persisted = await db.get(StrategyTargetApproval, approval_ref)
        assert persisted is not None
        assert persisted.state == "APPROVED"
        assert persisted.consumption_ref is None


@pytest.mark.asyncio
async def test_consume_without_trusted_current_state_provider_fails_closed():
    async with async_session_maker() as db:
        row = await _create_approval(db)
        claim = await _reserve(db, row)
        with pytest.raises(StrategyTargetApprovalError) as error:
            await consume_approved_target_v1(
                db,
                row.approval_ref,
                row.approval_version,
                row.target_sha256,
                operation_key=_OPERATION_KEY,
                intent_id=claim.intent_id,
                intent_sha256="f" * 64,
                owner_subject="subject-a",
                principal_ref="principal-a",
                expected_scope_ref="strategy-scope-a-v1",
                identity=_identity(),
                wire_scope=_wire_scope(),
                current_state_provider=None,
                now_ns=400,
            )
        assert error.value.code == "APPROVAL_POLICY_STALE"
        assert error.value.ambiguous is False


@pytest.mark.asyncio
async def test_expired_and_revoked_unreserved_targets_fail_closed():
    async with async_session_maker() as db:
        expired = await _create_approval(db)
        with pytest.raises(StrategyTargetApprovalError) as error:
            await _reserve(db, expired, now_ns=1_000)
        assert error.value.code == "APPROVAL_EXPIRED"

        revoked = await _create_approval(
            db,
            target=_target(target_ref="target-revoked"),
            approval_ref="approval-revoked",
        )
        version = await revoke_approved_order_target(
            db,
            approval_ref=revoked.approval_ref,
            approval_version=revoked.approval_version,
            owner_subject="subject-a",
            revoker_subject="approver-a",
            revoker_principal_ref="approval-principal",
            revoker_actor_ref="approval-console",
            revoker_delegate_ref=None,
            reason_code="operator_withdrawn",
            revoked_at_ns=300,
        )
        assert version == 2
        with pytest.raises(StrategyTargetApprovalError) as error:
            await _reserve(db, revoked, operation_key="revoked-key", now_ns=400)
        assert error.value.code == "APPROVAL_REVOKED"
        with pytest.raises(StrategyTargetApprovalError) as error:
            await consume_approved_target_v1(
                db,
                revoked.approval_ref,
                revoked.approval_version,
                revoked.target_sha256,
                operation_key="revoked-key",
                intent_id="not-reserved",
                intent_sha256="d" * 64,
                owner_subject="subject-a",
                principal_ref="principal-a",
                expected_scope_ref="strategy-scope-a-v1",
                identity=_identity(),
                wire_scope=_wire_scope(),
                current_state_provider=_SyntheticCurrentStateProvider(),
                now_ns=500,
            )
        assert error.value.code == "APPROVAL_OPERATION_CONFLICT"


@pytest.mark.asyncio
async def test_revocation_after_operation_reservation_wins_before_consume():
    async with async_session_maker() as db:
        row = await _create_approval(db)
        approval_ref = row.approval_ref
        approval_version = row.approval_version
        target_sha256 = row.target_sha256
        claim = await _reserve(db, row)
        version = await revoke_approved_order_target(
            db,
            approval_ref=approval_ref,
            approval_version=approval_version,
            owner_subject="subject-a",
            revoker_subject="approver-a",
            revoker_principal_ref="approval-principal",
            revoker_actor_ref="approval-console",
            revoker_delegate_ref=None,
            reason_code="withdrawn_before_dispatch",
            revoked_at_ns=300,
        )
        assert version == 3
        reservation_replay = await _reserve(db, row)
        assert reservation_replay.created is False
        assert reservation_replay.intent_id == claim.intent_id

        # The frozen target can be reconstructed for this existing operation;
        # this does not authorize dispatch, which still requires consume.
        resolved = await resolve_approved_target_v1(
            db,
            approval_ref,
            approval_version,
            target_sha256,
            operation_key=_OPERATION_KEY,
            intent_id=claim.intent_id,
            owner_subject="subject-a",
            principal_ref="principal-a",
            expected_scope_ref="strategy-scope-a-v1",
            identity=_identity(),
            wire_scope=_wire_scope(),
        )
        assert resolved == _target()

        with pytest.raises(StrategyTargetApprovalError) as error:
            await consume_approved_target_v1(
                db,
                approval_ref,
                approval_version,
                target_sha256,
                operation_key=_OPERATION_KEY,
                intent_id=claim.intent_id,
                intent_sha256="e" * 64,
                owner_subject="subject-a",
                principal_ref="principal-a",
                expected_scope_ref="strategy-scope-a-v1",
                identity=_identity(),
                wire_scope=_wire_scope(),
                current_state_provider=_SyntheticCurrentStateProvider(),
                now_ns=400,
            )
        assert error.value.code == "APPROVAL_REVOKED"
        assert error.value.ambiguous is False

        events = (
            await db.execute(
                select(StrategyTargetApprovalEvent)
                .where(StrategyTargetApprovalEvent.approval_ref == approval_ref)
                .order_by(StrategyTargetApprovalEvent.record_version)
            )
        ).scalars().all()
        assert [(event.event_type, event.record_version) for event in events] == [
            ("APPROVED", 1),
            ("OPERATION_RESERVED", 2),
            ("REVOKED", 3),
        ]
