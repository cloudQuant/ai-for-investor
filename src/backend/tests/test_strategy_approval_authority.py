"""Production-source checks for the AFI approved-target authority boundary."""

from __future__ import annotations

import asyncio
import importlib.util
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
import sqlalchemy as sa
from pydantic_settings import BaseSettings as _BaseSettings
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

_SYNTHETIC_ENV = {
    "DEBUG": "false",
    "DATABASE_URL": "sqlite+aiosqlite://",
    "SECRET_KEY": "strategy-authority-test-secret-0123456789",
    "ADMIN_PASSWORD": "StrategyAuthoritySyntheticAdmin!98765",
    "JWT_SECRET_KEY": "strategy-authority-test-jwt-secret-0123456789",
    "JWT_ALGORITHM": "HS256",
    "LOG_LEVEL": "CRITICAL",
    "LOG_DIR": tempfile.mkdtemp(prefix="afi_strategy_authority_"),
    "BT_API_LOG_DIR": tempfile.mkdtemp(prefix="afi_strategy_authority_sdk_"),
    "SQL_ECHO": "false",
    "AI_CHAT_ENABLED": "false",
    "AI_CHAT_BASE_URL": "",
    "AI_CHAT_API_KEY": "",
    "AI_CHAT_MODEL": "",
}
_ORIGINAL_ENV = os.environ
_ORIGINAL_SETTINGS_INIT = _BaseSettings.__init__


def _settings_without_dotenv(self, *args, **kwargs):
    kwargs["_env_file"] = None
    _ORIGINAL_SETTINGS_INIT(self, *args, **kwargs)


_BaseSettings.__init__ = _settings_without_dotenv
os.environ = dict(_SYNTHETIC_ENV)  # noqa: B003 - isolated synthetic DB/settings only
try:
    import app.models  # noqa: F401,E402
    from app.db.database import Base  # noqa: E402
    from app.models.portfolio_composition import PortfolioCompositionVersion  # noqa: E402
    from app.models.strategy import Strategy  # noqa: E402
    from app.models.strategy_approval_authority import (  # noqa: E402
        StrategyApprovalAuthorityEpoch,
        StrategyOrderApprovalPolicyHead,
        StrategyOrderApprovalPolicyVersion,
    )
    from app.models.strategy_version import StrategyVersion, VersionBranch  # noqa: E402
    from app.models.user import User  # noqa: E402
    from app.schemas.portfolio_composition import (  # noqa: E402
        PortfolioCompositionCreate,
        PortfolioCompositionMember,
    )
    from app.schemas.strategy_version import VersionUpdate  # noqa: E402
    from app.services.portfolio_composition import PortfolioCompositionService  # noqa: E402
    from app.services.strategy.version import VersionControlService  # noqa: E402
    from app.services.strategy_approval_authority import (
        StrategyOrderTargetCurrentStateProvider,
        approve_strategy_order_target,
        canonical_policy_sha256,
        lock_strategy_approval_authority_epoch,
        publish_strategy_order_approval_policy,
        strategy_version_content_sha256,
    )  # noqa: E402
    from app.services.strategy_target_approvals import (
        StrategyTargetApprovalError,
        consume_approved_target_v1,
        reserve_approved_target_operation,
    )  # noqa: E402
finally:
    _BaseSettings.__init__ = _ORIGINAL_SETTINGS_INIT
    os.environ = _ORIGINAL_ENV  # noqa: B003 - restore caller process settings


_TABLE_NAMES = (
    "users",
    "strategies",
    "strategy_versions",
    "strategy_branches",
    "portfolio_composition_versions",
    "strategy_target_approvals",
    "strategy_target_approval_events",
    "strategy_order_approval_policy_versions",
    "strategy_order_approval_policy_heads",
    "strategy_approval_authority_epochs",
)
_TABLES = [Base.metadata.tables[name] for name in _TABLE_NAMES]


@pytest_asyncio.fixture
async def authority_db(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'approval-authority.sqlite3'}",
        connect_args={"timeout": 10},
    )
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=_TABLES))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


def _policy(**changes):
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
    policy.update(changes)
    return policy


def _identity():
    return SimpleNamespace(
        role="application_client",
        principal_ref="principal-a",
        actor_ref="actor-a",
        delegate_ref="delegate-a",
    )


def _wire_scope():
    return SimpleNamespace(
        execution_domain_ref="paper:synthetic",
        account_ref="account-a",
        account_refs=(),
        strategy_ref="strategy-a",
        run_id=None,
        manual_book_ref=None,
        portfolio_ref=None,
        group_id=None,
        leg_id=None,
    )


def _target(policy_sha256: str, policy_version: int, target_ref: str = "strategy-order-target-a"):
    return {
        "schema_id": "bt_api.approved_order_target",
        "schema_version": 1,
        "target_ref": target_ref,
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
        "policy_version": policy_version,
        "policy_sha256": policy_sha256,
    }


async def _seed_user_strategy_version(factory):
    async with factory() as db:
        async with db.begin():
            db.add(
                User(
                    id="subject-a",
                    username="synthetic-authority-user",
                    email="synthetic-authority@example.invalid",
                    hashed_password="not-a-credential-test-data-only",
                    principal_kind="HUMAN",
                )
            )
            db.add(
                Strategy(
                    id="strategy-a",
                    user_id="subject-a",
                    name="synthetic strategy",
                    code="pass",
                    params={},
                )
            )
            version = StrategyVersion(
                id="strategy-version-a",
                strategy_id="strategy-a",
                version_number=7,
                version_name="v7",
                branch="main",
                status="stable",
                tags=["synthetic"],
                code="pass",
                params={"period": 5},
                is_active=True,
                is_default=False,
                is_current=True,
                created_by="subject-a",
            )
            db.add(version)
            await db.flush()
            db.add(
                VersionBranch(
                    id="strategy-main-branch",
                    strategy_id="strategy-a",
                    branch_name="main",
                    version_count=1,
                    last_version_id=version.id,
                    is_default=True,
                    created_by="subject-a",
                )
            )
    async with factory() as db:
        return await db.get(StrategyVersion, "strategy-version-a")


async def _publish_policy(db, policy=None, *, policy_ref="policy-a", at_ns=10):
    return await publish_strategy_order_approval_policy(
        db,
        owner_subject="subject-a",
        policy_ref=policy_ref,
        policy=_policy() if policy is None else policy,
        published_by_subject="subject-a",
        published_by_principal_ref="approval-principal",
        published_by_actor_ref="approval-console",
        published_by_delegate_ref=None,
        published_at_ns=at_ns,
    )


async def _approve(
    factory,
    *,
    expires_at_ns=1_000,
    target_ref="strategy-order-target-a",
):
    async with factory() as db:
        head = await db.get(StrategyOrderApprovalPolicyHead, "subject-a")
        assert head is not None
        row = await db.scalar(
            select(StrategyOrderApprovalPolicyVersion).where(
                StrategyOrderApprovalPolicyVersion.owner_subject == head.owner_subject,
                StrategyOrderApprovalPolicyVersion.policy_ref == head.policy_ref,
                StrategyOrderApprovalPolicyVersion.policy_version == head.policy_version,
            )
        )
        assert row is not None
        policy_sha256 = row.policy_sha256
        policy_version = row.policy_version
    async with factory() as db:
        return await approve_strategy_order_target(
            db,
            target=_target(policy_sha256, policy_version, target_ref),
            owner_subject="subject-a",
            expected_scope_ref="strategy-scope-a-v1",
            target_identity=_identity(),
            target_wire_scope=_wire_scope(),
            approved_by_subject="subject-a",
            approved_by_principal_ref="approval-principal",
            approved_by_actor_ref="approval-console",
            approved_by_delegate_ref=None,
            approved_at_ns=100,
            expires_at_ns=expires_at_ns,
        )


async def _reserve_and_consume(factory, approval, *, now_ns=400):
    async with factory() as db:
        claim = await reserve_approved_target_operation(
            db,
            approval_ref=approval.approval_ref,
            approval_version=approval.approval_version,
            target_sha256=approval.target_sha256,
            operation_key="approved-http-key-a",
            intent_id=f"intent-{approval.approval_ref}",
            owner_subject="subject-a",
            principal_ref="principal-a",
            expected_scope_ref="strategy-scope-a-v1",
            identity=_identity(),
            wire_scope=_wire_scope(),
            now_ns=200,
        )
        receipt = await consume_approved_target_v1(
            db,
            approval.approval_ref,
            approval.approval_version,
            approval.target_sha256,
            operation_key="approved-http-key-a",
            intent_id=claim.intent_id,
            intent_sha256="d" * 64,
            owner_subject="subject-a",
            principal_ref="principal-a",
            expected_scope_ref="strategy-scope-a-v1",
            identity=_identity(),
            wire_scope=_wire_scope(),
            current_state_provider=StrategyOrderTargetCurrentStateProvider(),
            now_ns=now_ns,
        )
    return claim, receipt


@pytest.mark.asyncio
async def test_approved_target_uses_real_policy_strategy_sources_and_consumes_once(authority_db):
    version = await _seed_user_strategy_version(authority_db)
    source_digest = strategy_version_content_sha256(version)
    async with authority_db() as db:
        await _publish_policy(db)
        await db.commit()

    approval = await _approve(authority_db)
    assert approval.strategy_version_source_id == "strategy-version-a"
    assert approval.strategy_version_branch == "main"
    assert approval.strategy_version_sha256 == source_digest
    claim, receipt = await _reserve_and_consume(authority_db, approval)
    assert claim.intent_id == f"intent-{approval.approval_ref}"
    assert receipt["disposition"] == "CONSUMED_NEW"
    assert receipt["intent_id"] == claim.intent_id

    async with authority_db() as db:
        replay = await consume_approved_target_v1(
            db,
            approval.approval_ref,
            approval.approval_version,
            approval.target_sha256,
            operation_key="approved-http-key-a",
            intent_id=claim.intent_id,
            intent_sha256="d" * 64,
            owner_subject="subject-a",
            principal_ref="principal-a",
            expected_scope_ref="strategy-scope-a-v1",
            identity=_identity(),
            wire_scope=_wire_scope(),
            current_state_provider=StrategyOrderTargetCurrentStateProvider(),
            now_ns=2_000,
        )
    assert replay["disposition"] == "ALREADY_CONSUMED"
    assert replay["consumption_ref"] == receipt["consumption_ref"]


@pytest.mark.asyncio
async def test_approved_target_rejects_policy_change_and_expiry(authority_db):
    await _seed_user_strategy_version(authority_db)
    async with authority_db() as db:
        policy = await _publish_policy(db)
        await db.commit()
    approval = await _approve(authority_db)
    async with authority_db() as db:
        claim = await reserve_approved_target_operation(
            db,
            approval_ref=approval.approval_ref,
            approval_version=approval.approval_version,
            target_sha256=approval.target_sha256,
            operation_key="approved-http-key-a",
            intent_id=f"intent-{approval.approval_ref}",
            owner_subject="subject-a",
            principal_ref="principal-a",
            expected_scope_ref="strategy-scope-a-v1",
            identity=_identity(),
            wire_scope=_wire_scope(),
            now_ns=200,
        )
        changed = _policy()
        changed["allowed_sides"] = ["SELL"]
        await _publish_policy(db, changed, at_ns=300)
        await db.commit()
        with pytest.raises(StrategyTargetApprovalError) as stale:
            await consume_approved_target_v1(
                db,
                approval.approval_ref,
                approval.approval_version,
                approval.target_sha256,
                operation_key="approved-http-key-a",
                intent_id=claim.intent_id,
                intent_sha256="d" * 64,
                owner_subject="subject-a",
                principal_ref="principal-a",
                expected_scope_ref="strategy-scope-a-v1",
                identity=_identity(),
                wire_scope=_wire_scope(),
                current_state_provider=StrategyOrderTargetCurrentStateProvider(),
                now_ns=400,
            )
        assert stale.value.code == "APPROVAL_POLICY_STALE"
        assert stale.value.ambiguous is False

    # A separate approved target proves expiry is checked at the consume gate,
    # after its exact stable intent has already been reserved.
    target_policy_hash = canonical_policy_sha256(_policy())
    assert policy.policy_sha256 == target_policy_hash
    async with authority_db() as db:
        await _publish_policy(db, at_ns=500)
        await db.commit()
    expired = await _approve(
        authority_db,
        expires_at_ns=700,
        target_ref="strategy-order-target-expiring",
    )
    async with authority_db() as db:
        claim = await reserve_approved_target_operation(
            db,
            approval_ref=expired.approval_ref,
            approval_version=expired.approval_version,
            target_sha256=expired.target_sha256,
            operation_key="approved-http-key-expired",
            intent_id=f"intent-{expired.approval_ref}",
            owner_subject="subject-a",
            principal_ref="principal-a",
            expected_scope_ref="strategy-scope-a-v1",
            identity=_identity(),
            wire_scope=_wire_scope(),
            now_ns=600,
        )
        with pytest.raises(StrategyTargetApprovalError) as expiry:
            await consume_approved_target_v1(
                db,
                expired.approval_ref,
                expired.approval_version,
                expired.target_sha256,
                operation_key="approved-http-key-expired",
                intent_id=claim.intent_id,
                intent_sha256="e" * 64,
                owner_subject="subject-a",
                principal_ref="principal-a",
                expected_scope_ref="strategy-scope-a-v1",
                identity=_identity(),
                wire_scope=_wire_scope(),
                current_state_provider=StrategyOrderTargetCurrentStateProvider(),
                now_ns=700,
            )
        assert expiry.value.code == "APPROVAL_EXPIRED"
        assert expiry.value.ambiguous is False


@pytest.mark.asyncio
async def test_unknown_provider_exception_code_remains_ambiguous(authority_db):
    await _seed_user_strategy_version(authority_db)
    async with authority_db() as db:
        await _publish_policy(db)
        await db.commit()
    approval = await _approve(authority_db)

    class UntrustedCodeError(RuntimeError):
        code = "APPROVAL_REVOKED"

    class UntrustedProvider:
        async def read_current_approval_state_v1(self, *args, **kwargs):
            raise UntrustedCodeError("synthetic provider failure")

    async with authority_db() as db:
        claim = await reserve_approved_target_operation(
            db,
            approval_ref=approval.approval_ref,
            approval_version=approval.approval_version,
            target_sha256=approval.target_sha256,
            operation_key="approved-http-key-ambiguous",
            intent_id=f"intent-{approval.approval_ref}",
            owner_subject="subject-a",
            principal_ref="principal-a",
            expected_scope_ref="strategy-scope-a-v1",
            identity=_identity(),
            wire_scope=_wire_scope(),
            now_ns=200,
        )
        with pytest.raises(StrategyTargetApprovalError) as error:
            await consume_approved_target_v1(
                db,
                approval.approval_ref,
                approval.approval_version,
                approval.target_sha256,
                operation_key="approved-http-key-ambiguous",
                intent_id=claim.intent_id,
                intent_sha256="f" * 64,
                owner_subject="subject-a",
                principal_ref="principal-a",
                expected_scope_ref="strategy-scope-a-v1",
                identity=_identity(),
                wire_scope=_wire_scope(),
                current_state_provider=UntrustedProvider(),
                now_ns=400,
            )
        assert type(error.value) is StrategyTargetApprovalError
        assert error.value.code == "APPROVAL_STORE_UNAVAILABLE"
        assert error.value.ambiguous is True


@pytest.mark.asyncio
async def test_sqlite_epoch_serializes_publishers_and_rolls_back_with_source(authority_db):
    await _seed_user_strategy_version(authority_db)

    async def publish_one(policy_ref: str):
        async with authority_db() as db:
            async with db.begin():
                row = await _publish_policy(db, policy_ref=policy_ref)
                # Keep the first SQLite write transaction open long enough for
                # the competing session to contend on the real epoch row.
                await asyncio.sleep(0.03)
                return row.policy_version

    versions = await asyncio.gather(publish_one("policy-concurrent"), publish_one("policy-concurrent"))
    assert sorted(versions) == [1, 2]
    async with authority_db() as db:
        epoch_before = await db.get(StrategyApprovalAuthorityEpoch, "subject-a")
        assert epoch_before is not None and epoch_before.epoch == 2
        head_before = await db.get(StrategyOrderApprovalPolicyHead, "subject-a")
        assert head_before is not None and head_before.policy_version == 2

    class RollbackSentinel(RuntimeError):
        pass

    with pytest.raises(RollbackSentinel):
        async with authority_db() as db:
            async with db.begin():
                await lock_strategy_approval_authority_epoch(db, "subject-a")
                version = await db.get(StrategyVersion, "strategy-version-a")
                assert version is not None
                version.code = "uncommitted mutation"
                from app.services.strategy_approval_authority import (
                    advance_strategy_approval_authority_epoch,
                )

                await advance_strategy_approval_authority_epoch(db, "subject-a")
                raise RollbackSentinel

    async with authority_db() as db:
        version = await db.get(StrategyVersion, "strategy-version-a")
        epoch_after = await db.get(StrategyApprovalAuthorityEpoch, "subject-a")
        assert version is not None and version.code == "pass"
        assert epoch_after is not None and epoch_after.epoch == 2


@pytest.mark.asyncio
async def test_version_and_membership_writers_share_source_transaction_with_epoch(authority_db):
    await _seed_user_strategy_version(authority_db)
    async with authority_db() as db:
        service = VersionControlService(session=db)
        new_version = await service.create_version(
            user_id="subject-a",
            strategy_id="strategy-a",
            version_name="v8",
            code="next",
            params={"period": 7},
            branch="main",
        )
        branch = await db.scalar(
            select(VersionBranch).where(
                VersionBranch.strategy_id == "strategy-a",
                VersionBranch.branch_name == "main",
            )
        )
        epoch = await db.get(StrategyApprovalAuthorityEpoch, "subject-a")
        assert branch is not None and branch.last_version_id == new_version.id
        assert branch.version_count == 2
        assert epoch is not None and epoch.epoch == 1

    async with authority_db() as db:
        request = PortfolioCompositionCreate(
            portfolio_ref="research-portfolio-a",
            source_type="research",
            base_currency="USD",
            members=[PortfolioCompositionMember(kind="research_artifact", ref="artifact-a")],
        )
        row = await PortfolioCompositionService(db).create_version("subject-a", request)
        persisted_epoch = await db.get(StrategyApprovalAuthorityEpoch, "subject-a")
        assert row.membership_version == 1
        assert row.membership_sha256
        assert persisted_epoch is not None and persisted_epoch.epoch == 2


@pytest.mark.asyncio
async def test_version_mutations_require_the_strategy_owner(authority_db):
    await _seed_user_strategy_version(authority_db)
    async with authority_db() as db:
        async with db.begin():
            db.add(
                User(
                    id="subject-b",
                    username="synthetic-secondary-user",
                    email="synthetic-secondary@example.invalid",
                    hashed_password="not-a-credential-test-data-only",
                    principal_kind="HUMAN",
                )
            )
            db.add(
                StrategyVersion(
                    id="foreign-created-draft",
                    strategy_id="strategy-a",
                    version_number=8,
                    version_name="v8-draft",
                    branch="main",
                    status="draft",
                    tags=[],
                    code="original",
                    params={},
                    is_active=False,
                    is_default=False,
                    is_current=False,
                    created_by="subject-b",
                )
            )

    async with authority_db() as db:
        service = VersionControlService(session=db)
        assert (
            await service.update_version(
                "foreign-created-draft", "subject-b", VersionUpdate(code="modified")
            )
            is None
        )
        assert not await service.activate_version("foreign-created-draft", "subject-b")

    async with authority_db() as db:
        foreign_version = await db.get(StrategyVersion, "foreign-created-draft")
        owner_version = await db.get(StrategyVersion, "strategy-version-a")
        owner_epoch = await db.get(StrategyApprovalAuthorityEpoch, "subject-a")
        creator_epoch = await db.get(StrategyApprovalAuthorityEpoch, "subject-b")
        assert foreign_version is not None
        assert foreign_version.code == "original"
        assert foreign_version.is_active is False
        assert owner_version is not None and owner_version.is_active is True
        assert owner_epoch is None
        assert creator_epoch is not None and creator_epoch.epoch == 0


@pytest.mark.asyncio
async def test_membership_failure_rolls_back_pending_row_and_epoch(authority_db, monkeypatch):
    await _seed_user_strategy_version(authority_db)
    from app.services.strategy_approval_authority import StrategyTargetApprovalError

    monkeypatch.setattr(
        "app.services.strategy_approval_authority.advance_strategy_approval_authority_epoch",
        AsyncMock(side_effect=StrategyTargetApprovalError("APPROVAL_POLICY_STALE")),
    )
    request = PortfolioCompositionCreate(
        portfolio_ref="research-portfolio-failed",
        source_type="research",
        base_currency="USD",
        members=[PortfolioCompositionMember(kind="research_artifact", ref="artifact-failed")],
    )
    async with authority_db() as db:
        with pytest.raises(StrategyTargetApprovalError, match="APPROVAL_POLICY_STALE"):
            await PortfolioCompositionService(db).create_version("subject-a", request)
        assert not db.in_transaction()

    async with authority_db() as db:
        memberships = await db.scalars(select(PortfolioCompositionVersion))
        epoch = await db.get(StrategyApprovalAuthorityEpoch, "subject-a")
        assert memberships.all() == []
        assert epoch is None


def test_branch_head_migration_rejects_duplicate_and_mismatched_pointers():
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "20261016_strategy_approval_authority_sources.py"
    )
    spec = importlib.util.spec_from_file_location("strategy_authority_revision", migration_path)
    assert spec is not None and spec.loader is not None
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    versions = sa.Table(
        "strategy_versions",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("strategy_id", sa.String(36), nullable=False),
        sa.Column("branch", sa.String(50), nullable=True),
        sa.Column("version_number", sa.Integer(), nullable=False),
    )
    branches = sa.Table(
        "strategy_branches",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("strategy_id", sa.String(36), nullable=False),
        sa.Column("branch_name", sa.String(50), nullable=False),
        sa.Column("version_count", sa.Integer(), nullable=False),
        sa.Column("last_version_id", sa.String(36)),
    )
    try:
        metadata.create_all(engine)
        with engine.begin() as connection:
            connection.execute(
                versions.insert(),
                {
                    "id": "version-a",
                    "strategy_id": "strategy-a",
                    "branch": "main",
                    "version_number": 1,
                },
            )
            connection.execute(
                branches.insert(),
                {
                    "id": "branch-a",
                    "strategy_id": "strategy-a",
                    "branch_name": "main",
                    "version_count": 1,
                    "last_version_id": "version-a",
                },
            )
            revision._validate_existing_branch_heads(connection)
            connection.execute(
                branches.insert(),
                {
                    "id": "branch-b",
                    "strategy_id": "strategy-a",
                    "branch_name": "main",
                    "version_count": 1,
                    "last_version_id": "version-a",
                },
            )
            with pytest.raises(RuntimeError, match="duplicate branch"):
                revision._validate_existing_branch_heads(connection)
        with engine.begin() as connection:
            connection.execute(branches.delete())
            connection.execute(
                branches.insert(),
                {
                    "id": "branch-mismatch",
                    "strategy_id": "strategy-a",
                    "branch_name": "other",
                    "version_count": 1,
                    "last_version_id": "version-a",
                },
            )
            with pytest.raises(RuntimeError, match="mismatched pointer"):
                revision._validate_existing_branch_heads(connection)
        with engine.begin() as connection:
            connection.execute(branches.delete())
            connection.execute(
                versions.insert(),
                {
                    "id": "version-newer",
                    "strategy_id": "strategy-a",
                    "branch": "main",
                    "version_number": 2,
                },
            )
            connection.execute(
                branches.insert(),
                {
                    "id": "branch-stale-head",
                    "strategy_id": "strategy-a",
                    "branch_name": "main",
                    "version_count": 2,
                    "last_version_id": "version-a",
                },
            )
            with pytest.raises(RuntimeError, match="mismatched pointer"):
                revision._validate_existing_branch_heads(connection)
        with engine.begin() as connection:
            connection.execute(branches.delete())
            connection.execute(versions.delete())
            connection.execute(
                versions.insert(),
                {
                    "id": "version-unheaded",
                    "strategy_id": "strategy-a",
                    "branch": "main",
                    "version_number": 1,
                },
            )
            connection.execute(
                branches.insert(),
                {
                    "id": "branch-unheaded",
                    "strategy_id": "strategy-a",
                    "branch_name": "main",
                    "version_count": 0,
                    "last_version_id": None,
                },
            )
            with pytest.raises(RuntimeError, match="mismatched pointer"):
                revision._validate_existing_branch_heads(connection)
        with engine.begin() as connection:
            connection.execute(branches.delete())
            connection.execute(versions.delete())
            connection.execute(
                versions.insert(),
                {
                    "id": "version-null-branch",
                    "strategy_id": "strategy-a",
                    "branch": None,
                    "version_number": 1,
                },
            )
            connection.execute(
                branches.insert(),
                {
                    "id": "branch-null-branch-pointer",
                    "strategy_id": "strategy-a",
                    "branch_name": "main",
                    "version_count": 1,
                    "last_version_id": "version-null-branch",
                },
            )
            with pytest.raises(RuntimeError, match="mismatched pointer"):
                revision._validate_existing_branch_heads(connection)
    finally:
        engine.dispose()
