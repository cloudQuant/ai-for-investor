"""Persisted approved-target role boundary for owner.reduce consumption."""

from __future__ import annotations

import os
import tempfile

import pytest
import pytest_asyncio
from pydantic_settings import BaseSettings as _BaseSettings
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

_SYNTHETIC_ENV = {
    "DEBUG": "false",
    "DATABASE_URL": "sqlite+aiosqlite://",
    "SECRET_KEY": "strategy-reduction-identity-test-secret-0123456789",
    "ADMIN_PASSWORD": "StrategyReductionSyntheticAdmin!98765",
    "JWT_SECRET_KEY": "strategy-reduction-identity-jwt-secret-0123456789",
    "JWT_ALGORITHM": "HS256",
    "LOG_LEVEL": "CRITICAL",
    "LOG_DIR": tempfile.mkdtemp(prefix="afi_strategy_reduction_identity_"),
    "BT_API_LOG_DIR": tempfile.mkdtemp(prefix="afi_strategy_reduction_sdk_"),
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
os.environ = dict(_SYNTHETIC_ENV)  # noqa: B003 - isolate synthetic DB/settings only
try:
    import app.models  # noqa: F401,E402
    from app.db.database import Base  # noqa: E402
    from app.models.strategy import Strategy  # noqa: E402
    from app.models.strategy_target_approval import (  # noqa: E402
        StrategyTargetApproval,
        StrategyTargetApprovalEvent,
    )
    from app.models.strategy_version import StrategyVersion, VersionBranch  # noqa: E402
    from app.models.user import User  # noqa: E402
    from app.services.strategy_approval_authority import (  # noqa: E402
        StrategyOrderTargetCurrentStateProvider,
        approve_strategy_order_target,
        publish_strategy_order_approval_policy,
    )
    from app.services.strategy_target_approvals import (  # noqa: E402
        StrategyTargetApprovalError,
        canonical_target_sha256,
        create_approved_order_target,
        consume_approved_target_v1,
        reserve_approved_target_operation,
        resolve_approved_target_v1,
    )
    from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope  # noqa: E402
finally:
    _BaseSettings.__init__ = _ORIGINAL_SETTINGS_INIT
    os.environ = _ORIGINAL_ENV  # noqa: B003 - restore caller environment


_TABLES = [
    Base.metadata.tables[name]
    for name in (
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
]
_OWNER = "owner-subject"
_PRINCIPAL = "owner-service-principal"
_ACTOR = "strategy-owner-actor"
_DELEGATE = "owner-service-delegate"
_SCOPE_REF = "strategy-run-close"
_SCOPE = WireScope(
    execution_domain_ref="paper:synthetic",
    account_ref="account-a",
    strategy_ref="strategy-a",
    run_id="run-a",
)


def _identity(role: WireRole, *, actor: str = _ACTOR, delegate: str | None = _DELEGATE) -> WireIdentity:
    return WireIdentity(
        role=role,
        principal_ref=_PRINCIPAL,
        actor_ref=actor,
        delegate_ref=delegate,
    )


def _target(target_ref: str, *, close_only: bool, policy_sha256: str, policy_version: int) -> dict[str, object]:
    return {
        "schema_id": "bt_api.approved_order_target",
        "schema_version": 1,
        "target_ref": target_ref,
        "target_version": 1,
        "owner_subject": _OWNER,
        "principal_ref": _PRINCIPAL,
        "actor_ref": _ACTOR,
        "delegate_ref": _DELEGATE,
        "scope_ref": _SCOPE_REF,
        "wire_scope": {
            "execution_domain_ref": _SCOPE.execution_domain_ref,
            "account_ref": _SCOPE.account_ref,
            "account_refs": [],
            "strategy_ref": _SCOPE.strategy_ref,
            "run_id": _SCOPE.run_id,
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
        "side": "SELL" if close_only else "BUY",
        "position_effect": "CLOSE" if close_only else "OPEN",
        "order_type": "LIMIT",
        "quantity": "1",
        "price": "100",
        "time_in_force": "GTC",
        "reduce_only": close_only,
        "deadline_ns": None,
        "limits": {
            "max_quantity": "1",
            "max_notional": "100",
            "min_price": "1",
            "max_price": "200",
        },
        "policy_ref": "policy-a",
        "policy_version": policy_version,
        "policy_sha256": policy_sha256,
    }


async def _seed_sources(factory) -> tuple[str, int]:
    async with factory() as db:
        async with db.begin():
            db.add(
                User(
                    id=_OWNER,
                    username="synthetic-reduction-owner",
                    email="synthetic-reduction-owner@example.invalid",
                    hashed_password="test-data-not-a-credential",
                    principal_kind="HUMAN",
                )
            )
            db.add(
                Strategy(
                    id="strategy-a",
                    user_id=_OWNER,
                    name="synthetic reduction strategy",
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
                created_by=_OWNER,
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
                    created_by=_OWNER,
                )
            )

    policy = {
        "schema_id": "afi.strategy_order_approval_policy",
        "schema_version": 1,
        "allowed_instruments": ["BTC-USDT"],
        "allowed_sides": ["BUY", "SELL"],
        "allowed_position_effects": ["OPEN", "CLOSE"],
        "allowed_order_types": ["LIMIT"],
        "allowed_time_in_force": ["GTC"],
        "limits": {
            "max_quantity": "1",
            "max_notional": "100",
            "min_price": "1",
            "max_price": "200",
        },
    }
    async with factory() as db:
        row = await publish_strategy_order_approval_policy(
            db,
            owner_subject=_OWNER,
            policy_ref="policy-a",
            policy=policy,
            published_by_subject=_OWNER,
            published_by_principal_ref="human-approver",
            published_by_actor_ref="approval-http",
            published_by_delegate_ref=None,
            published_at_ns=50,
        )
        await db.commit()
        return row.policy_sha256, row.policy_version


async def _approve_target(factory, *, target_ref: str, close_only: bool, policy_sha256: str, policy_version: int):
    target = _target(
        target_ref,
        close_only=close_only,
        policy_sha256=policy_sha256,
        policy_version=policy_version,
    )
    async with factory() as db:
        return await approve_strategy_order_target(
            db,
            target=target,
            owner_subject=_OWNER,
            expected_scope_ref=_SCOPE_REF,
            target_identity=_identity(WireRole.APPLICATION_CLIENT),
            target_wire_scope=_SCOPE,
            approved_by_subject=_OWNER,
            approved_by_principal_ref="human-approver",
            approved_by_actor_ref="approval-http",
            approved_by_delegate_ref=None,
            approved_at_ns=100,
            expires_at_ns=10_000,
        )


async def _reject_target_for_service(db, target: dict[str, object]) -> None:
    await create_approved_order_target(
        db,
        target=target,
        target_sha256=canonical_target_sha256(target),
        approval_ref="approval-service-created",
        approval_version=1,
        owner_subject=_OWNER,
        expected_scope_ref=_SCOPE_REF,
        target_identity=_identity(WireRole.SERVICE),
        target_wire_scope=_SCOPE,
        approved_by_subject=_OWNER,
        approved_by_principal_ref="human-approver",
        approved_by_actor_ref="approval-http",
        approved_by_delegate_ref=None,
        approved_at_ns=100,
        expires_at_ns=10_000,
    )


@pytest_asyncio.fixture
async def approval_sessions(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'owner-reduction-approval.sqlite3'}",
        connect_args={"timeout": 10},
    )
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=_TABLES))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_service_identity_can_consume_only_exact_persisted_close_target(approval_sessions):
    application_identity = _identity(WireRole.APPLICATION_CLIENT)
    service_identity = _identity(WireRole.SERVICE)
    policy_sha256, policy_version = await _seed_sources(approval_sessions)
    close_approval = await _approve_target(
        approval_sessions,
        target_ref="target-close",
        close_only=True,
        policy_sha256=policy_sha256,
        policy_version=policy_version,
    )
    open_approval = await _approve_target(
        approval_sessions,
        target_ref="target-open",
        close_only=False,
        policy_sha256=policy_sha256,
        policy_version=policy_version,
    )
    close_target = _target(
        "target-close",
        close_only=True,
        policy_sha256=policy_sha256,
        policy_version=policy_version,
    )

    # Target creation remains an application decision. SERVICE may only
    # consume an already persisted CLOSE/reduce-only target through its exact
    # code-owned execution binding.
    async with approval_sessions() as db:
        with pytest.raises(StrategyTargetApprovalError) as create_error:
            await _reject_target_for_service(
                db,
                _target(
                    "target-service-created",
                    close_only=True,
                    policy_sha256=policy_sha256,
                    policy_version=policy_version,
                ),
            )
        assert create_error.value.code == "APPROVAL_IDENTITY_MISMATCH"

        claim = await reserve_approved_target_operation(
            db,
            approval_ref=close_approval.approval_ref,
            approval_version=close_approval.approval_version,
            target_sha256=close_approval.target_sha256,
            operation_key="http-close-key",
            intent_id="intent-close-a",
            owner_subject=_OWNER,
            principal_ref=_PRINCIPAL,
            expected_scope_ref=_SCOPE_REF,
            identity=service_identity,
            wire_scope=_SCOPE,
            now_ns=200,
        )
        resolved = await resolve_approved_target_v1(
            db,
            close_approval.approval_ref,
            close_approval.approval_version,
            close_approval.target_sha256,
            operation_key="http-close-key",
            intent_id=claim.intent_id,
            owner_subject=_OWNER,
            principal_ref=_PRINCIPAL,
            expected_scope_ref=_SCOPE_REF,
            identity=service_identity,
            wire_scope=_SCOPE,
        )
        assert claim.created is True
        assert resolved == close_target

        # The application identity remains compatible with persisted reads.
        app_resolved = await resolve_approved_target_v1(
            db,
            close_approval.approval_ref,
            close_approval.approval_version,
            close_approval.target_sha256,
            operation_key="http-close-key",
            intent_id=claim.intent_id,
            owner_subject=_OWNER,
            principal_ref=_PRINCIPAL,
            expected_scope_ref=_SCOPE_REF,
            identity=application_identity,
            wire_scope=_SCOPE,
        )
        assert app_resolved == close_target

        wrong_claims = (
            (
                _identity(WireRole.SERVICE, actor="different-actor"),
                _SCOPE,
                "APPROVAL_IDENTITY_MISMATCH",
            ),
            (
                _identity(WireRole.SERVICE, delegate="different-delegate"),
                _SCOPE,
                "APPROVAL_IDENTITY_MISMATCH",
            ),
            (
                service_identity,
                WireScope(
                    execution_domain_ref="paper:synthetic",
                    account_ref="account-a",
                    strategy_ref="strategy-a",
                    run_id="run-b",
                ),
                "APPROVAL_SCOPE_MISMATCH",
            ),
        )
        for wrong_identity, wrong_scope, expected_code in wrong_claims:
            with pytest.raises(StrategyTargetApprovalError) as mismatch:
                await resolve_approved_target_v1(
                    db,
                    close_approval.approval_ref,
                    close_approval.approval_version,
                    close_approval.target_sha256,
                    operation_key="http-close-key",
                    intent_id=claim.intent_id,
                    owner_subject=_OWNER,
                    principal_ref=_PRINCIPAL,
                    expected_scope_ref=_SCOPE_REF,
                    identity=wrong_identity,
                    wire_scope=wrong_scope,
                )
            assert mismatch.value.code == expected_code

        with pytest.raises(StrategyTargetApprovalError) as open_error:
            await reserve_approved_target_operation(
                db,
                approval_ref=open_approval.approval_ref,
                approval_version=open_approval.approval_version,
                target_sha256=open_approval.target_sha256,
                operation_key="http-open-key",
                intent_id="intent-open-a",
                owner_subject=_OWNER,
                principal_ref=_PRINCIPAL,
                expected_scope_ref=_SCOPE_REF,
                identity=service_identity,
                wire_scope=_SCOPE,
                now_ns=200,
            )
        assert open_error.value.code == "APPROVAL_IDENTITY_MISMATCH"

        open_row = await db.get(StrategyTargetApproval, open_approval.approval_ref)
        assert open_row is not None
        assert open_row.operation_key_sha256 is None

    async with approval_sessions() as db:
        receipt = await consume_approved_target_v1(
            db,
            close_approval.approval_ref,
            close_approval.approval_version,
            close_approval.target_sha256,
            operation_key="http-close-key",
            intent_id=claim.intent_id,
            intent_sha256="d" * 64,
            owner_subject=_OWNER,
            principal_ref=_PRINCIPAL,
            expected_scope_ref=_SCOPE_REF,
            identity=service_identity,
            wire_scope=_SCOPE,
            current_state_provider=StrategyOrderTargetCurrentStateProvider(),
            now_ns=300,
        )
    assert receipt["disposition"] == "CONSUMED_NEW"
    assert receipt["intent_id"] == claim.intent_id

    async with approval_sessions() as db:
        replay = await consume_approved_target_v1(
            db,
            close_approval.approval_ref,
            close_approval.approval_version,
            close_approval.target_sha256,
            operation_key="http-close-key",
            intent_id=claim.intent_id,
            intent_sha256="d" * 64,
            owner_subject=_OWNER,
            principal_ref=_PRINCIPAL,
            expected_scope_ref=_SCOPE_REF,
            identity=service_identity,
            wire_scope=_SCOPE,
            current_state_provider=StrategyOrderTargetCurrentStateProvider(),
            now_ns=400,
        )
        stored = await db.get(StrategyTargetApproval, close_approval.approval_ref)
    assert replay["disposition"] == "ALREADY_CONSUMED"
    assert replay["consumption_ref"] == receipt["consumption_ref"]
    assert stored is not None and stored.state == "CONSUMED"
