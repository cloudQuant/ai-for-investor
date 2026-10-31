"""AFI-owned freshness sources for approved strategy order targets.

This module stores AFI approval policy and serializes mutable strategy and
membership facts. It does not represent or replace Execution/Risk admission.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select, update
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.portfolio_composition import PortfolioCompositionVersion
from app.models.strategy import Strategy
from app.models.strategy_approval_authority import (
    StrategyApprovalAuthorityEpoch,
    StrategyOrderApprovalPolicyHead,
    StrategyOrderApprovalPolicyVersion,
)
from app.models.strategy_target_approval import StrategyTargetApproval
from app.models.strategy_version import StrategyVersion, VersionBranch, VersionStatus
from app.services.strategy_target_approvals import (
    ApprovedTargetCurrentStateV1,
    StrategyTargetApprovalError,
    _delegate_storage_value,
    _identity_field,
    _identity_role,
    _scope_payload,
    _target_from_row,
    _validate_target,
    canonical_target_sha256,
    create_approved_order_target,
)

_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_DECIMAL_RE = re.compile(r"^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")
_INSTRUMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,191}$")
_ENUMS = {
    "allowed_sides": frozenset({"BUY", "SELL"}),
    "allowed_position_effects": frozenset(
        {"OPEN", "CLOSE", "CLOSE_TODAY", "CLOSE_YESTERDAY"}
    ),
    "allowed_order_types": frozenset({"MARKET", "LIMIT"}),
    "allowed_time_in_force": frozenset({"GTC", "IOC", "FOK", "DAY"}),
}
_POLICY_KEYS = frozenset(
    {
        "schema_id",
        "schema_version",
        "allowed_instruments",
        "allowed_sides",
        "allowed_position_effects",
        "allowed_order_types",
        "allowed_time_in_force",
        "limits",
    }
)
_LIMIT_KEYS = frozenset({"max_quantity", "max_notional", "min_price", "max_price"})


def canonical_policy_json(policy: Mapping[str, object]) -> str:
    normalized = _validate_policy(policy)
    try:
        return json.dumps(
            normalized,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError):
        raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID") from None


def canonical_policy_sha256(policy: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_policy_json(policy).encode("utf-8")).hexdigest()


def strategy_version_content_sha256(version: StrategyVersion) -> str:
    document = {
        "code": version.code,
        "params": version.params or {},
        "tags": version.tags or [],
    }
    try:
        encoded = json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise StrategyTargetApprovalError("APPROVAL_POLICY_STALE") from None
    return hashlib.sha256(encoded).hexdigest()


def portfolio_membership_sha256(row: PortfolioCompositionVersion) -> str:
    members = row.members
    if not isinstance(members, list):
        raise StrategyTargetApprovalError("APPROVAL_POLICY_STALE")
    document = {
        "source_type": row.source_type,
        "base_currency": row.base_currency,
        "members": members,
    }
    try:
        encoded = json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise StrategyTargetApprovalError("APPROVAL_POLICY_STALE") from None
    return hashlib.sha256(encoded).hexdigest()


async def lock_strategy_approval_authority_epoch(
    db: AsyncSession, owner_subject: str
) -> StrategyApprovalAuthorityEpoch:
    """Create-if-needed and exclusively lock the owner's freshness epoch.

    PostgreSQL/MySQL use row locks. SQLite's conflict-safe insert/update takes
    its write reservation before any caller performs source reads, equivalent
    to the required `BEGIN IMMEDIATE` ordering for this transaction.
    """

    if type(owner_subject) is not str or not owner_subject or len(owner_subject) > 256:
        raise StrategyTargetApprovalError("APPROVAL_OWNER_BINDING_MISMATCH")
    try:
        dialect = db.get_bind().dialect.name
        values = {
            "owner_subject": owner_subject,
            "epoch": 0,
            "updated_at": datetime.now(timezone.utc),
        }
        if dialect == "sqlite":
            await db.execute(
                sqlite_insert(StrategyApprovalAuthorityEpoch)
                .values(**values)
                .on_conflict_do_nothing(index_elements=["owner_subject"])
            )
            await db.execute(
                update(StrategyApprovalAuthorityEpoch)
                .where(StrategyApprovalAuthorityEpoch.owner_subject == owner_subject)
                .values(epoch=StrategyApprovalAuthorityEpoch.epoch)
            )
        elif dialect == "postgresql":
            await db.execute(
                postgresql_insert(StrategyApprovalAuthorityEpoch)
                .values(**values)
                .on_conflict_do_nothing(index_elements=["owner_subject"])
            )
        elif dialect == "mysql":
            await db.execute(
                mysql_insert(StrategyApprovalAuthorityEpoch)
                .values(**values)
                .prefix_with("IGNORE")
            )
        else:
            raise StrategyTargetApprovalError(
                "APPROVAL_STORE_UNAVAILABLE", ambiguous=True
            )
        result = await db.execute(
            select(StrategyApprovalAuthorityEpoch)
            .where(StrategyApprovalAuthorityEpoch.owner_subject == owner_subject)
            .with_for_update()
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise StrategyTargetApprovalError("APPROVAL_STORE_UNAVAILABLE", ambiguous=True)
        return row
    except StrategyTargetApprovalError:
        raise
    except SQLAlchemyError:
        raise StrategyTargetApprovalError("APPROVAL_STORE_UNAVAILABLE", ambiguous=True) from None


async def advance_strategy_approval_authority_epoch(
    db: AsyncSession, owner_subject: str
) -> int:
    """Increment the epoch after its source rows changed in this transaction."""

    epoch = await lock_strategy_approval_authority_epoch(db, owner_subject)
    next_epoch = epoch.epoch + 1
    try:
        result = await db.execute(
            update(StrategyApprovalAuthorityEpoch)
            .where(
                StrategyApprovalAuthorityEpoch.owner_subject == owner_subject,
                StrategyApprovalAuthorityEpoch.epoch == epoch.epoch,
            )
            .values(epoch=next_epoch, updated_at=datetime.now(timezone.utc))
        )
        if result.rowcount != 1:
            raise StrategyTargetApprovalError("APPROVAL_STORE_UNAVAILABLE", ambiguous=True)
        epoch.epoch = next_epoch
        return next_epoch
    except StrategyTargetApprovalError:
        raise
    except SQLAlchemyError:
        raise StrategyTargetApprovalError("APPROVAL_STORE_UNAVAILABLE", ambiguous=True) from None


async def publish_strategy_order_approval_policy(
    db: AsyncSession,
    *,
    owner_subject: str,
    policy_ref: str,
    policy: Mapping[str, object],
    published_by_subject: str,
    published_by_principal_ref: str,
    published_by_actor_ref: str,
    published_by_delegate_ref: str | None,
    published_at_ns: int,
) -> StrategyOrderApprovalPolicyVersion:
    """Publish a new immutable AFI policy and atomically advance its head.

    The caller owns the transaction and must commit after this returns. The
    caller must have enforced the dedicated policy-management permission.
    """

    _required_identifier(owner_subject, 256)
    _required_identifier(policy_ref, 128)
    _required_identifier(published_by_subject, 256)
    _required_identifier(published_by_principal_ref, 128)
    _required_identifier(published_by_actor_ref, 128)
    if published_by_delegate_ref is not None:
        _required_identifier(published_by_delegate_ref, 128)
    if type(published_at_ns) is not int or published_at_ns <= 0:
        raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID")
    await lock_strategy_approval_authority_epoch(db, owner_subject)
    normalized = _validate_policy(policy)
    policy_json = canonical_policy_json(normalized)
    policy_hash = hashlib.sha256(policy_json.encode("utf-8")).hexdigest()
    try:
        latest = await db.scalar(
            select(func.max(StrategyOrderApprovalPolicyVersion.policy_version)).where(
                StrategyOrderApprovalPolicyVersion.owner_subject == owner_subject,
                StrategyOrderApprovalPolicyVersion.policy_ref == policy_ref,
            )
        )
        version_number = (latest or 0) + 1
        row = StrategyOrderApprovalPolicyVersion(
            id=str(uuid.uuid4()),
            owner_subject=owner_subject,
            policy_ref=policy_ref,
            policy_version=version_number,
            policy_sha256=policy_hash,
            canonical_policy_json=policy_json,
            published_by_subject=published_by_subject,
            published_by_principal_ref=published_by_principal_ref,
            published_by_actor_ref=published_by_actor_ref,
            published_by_delegate_ref=published_by_delegate_ref or "",
            published_at_ns=published_at_ns,
        )
        db.add(row)
        await db.flush()
        head = await db.get(StrategyOrderApprovalPolicyHead, owner_subject, with_for_update=True)
        if head is None:
            head = StrategyOrderApprovalPolicyHead(
                owner_subject=owner_subject,
                policy_ref=policy_ref,
                policy_version=version_number,
                policy_sha256=policy_hash,
                head_version=1,
                updated_at=datetime.now(timezone.utc),
            )
            db.add(head)
        else:
            head.policy_ref = policy_ref
            head.policy_version = version_number
            head.policy_sha256 = policy_hash
            head.head_version += 1
            head.updated_at = datetime.now(timezone.utc)
        await advance_strategy_approval_authority_epoch(db, owner_subject)
        await db.flush()
        return row
    except StrategyTargetApprovalError:
        raise
    except SQLAlchemyError:
        raise StrategyTargetApprovalError("APPROVAL_STORE_UNAVAILABLE", ambiguous=True) from None


class StrategyOrderTargetCurrentStateProvider:
    """Resolve real AFI policy, strategy version and optional membership facts."""

    async def read_current_approval_state_v1(
        self,
        db: AsyncSession,
        approval_ref: str,
        approval_version: int,
        target_sha256: str,
        *,
        owner_subject: str,
        principal_ref: str,
        expected_scope_ref: str,
        identity: object,
        wire_scope: object,
    ) -> ApprovedTargetCurrentStateV1:
        del principal_ref, identity
        if not db.in_transaction():
            raise StrategyTargetApprovalError("APPROVAL_POLICY_STALE")
        try:
            # The same owner epoch is locked by every supported freshness
            # writer. This must precede every source read and remain locked
            # until the caller's approval CAS commits.
            await lock_strategy_approval_authority_epoch(db, owner_subject)
            approval = await db.get(StrategyTargetApproval, approval_ref)
            if (
                approval is None
                or approval.approval_version != approval_version
                or approval.target_sha256 != target_sha256
                or approval.owner_subject != owner_subject
                or approval.scope_ref != expected_scope_ref
                or approval.strategy_version_source_id is None
                or approval.strategy_version_branch is None
                or approval.strategy_version_sha256 is None
                or not _HASH_RE.fullmatch(approval.strategy_version_sha256)
            ):
                raise StrategyTargetApprovalError("APPROVAL_POLICY_STALE")
            target = _target_from_row(approval)
            wire = target["wire_scope"]
            if not isinstance(wire, dict) or wire != _wire_scope_mapping(wire_scope):
                raise StrategyTargetApprovalError("APPROVAL_POLICY_STALE")

            strategy = await db.get(Strategy, approval.strategy_ref)
            if strategy is None or strategy.user_id != owner_subject:
                raise StrategyTargetApprovalError("APPROVAL_POLICY_STALE")
            version = await db.get(StrategyVersion, approval.strategy_version_source_id)
            if (
                version is None
                or version.strategy_id != strategy.id
                or version.branch != approval.strategy_version_branch
                or version.version_number != approval.strategy_version
                or version.status != VersionStatus.STABLE.value
                or version.is_active is not True
                or strategy_version_content_sha256(version) != approval.strategy_version_sha256
            ):
                raise StrategyTargetApprovalError("APPROVAL_POLICY_STALE")

            branch_result = await db.execute(
                select(VersionBranch).where(
                    VersionBranch.strategy_id == strategy.id,
                    VersionBranch.branch_name == approval.strategy_version_branch,
                )
            )
            branches = branch_result.scalars().all()
            if len(branches) != 1 or branches[0].last_version_id != version.id:
                raise StrategyTargetApprovalError("APPROVAL_POLICY_STALE")

            head = await db.get(StrategyOrderApprovalPolicyHead, owner_subject)
            if (
                head is None
                or head.policy_ref != approval.policy_ref
                or head.policy_version != approval.policy_version
                or head.policy_sha256 != approval.policy_sha256
            ):
                raise StrategyTargetApprovalError("APPROVAL_POLICY_STALE")
            policy = await db.scalar(
                select(StrategyOrderApprovalPolicyVersion).where(
                    StrategyOrderApprovalPolicyVersion.owner_subject == owner_subject,
                    StrategyOrderApprovalPolicyVersion.policy_ref == head.policy_ref,
                    StrategyOrderApprovalPolicyVersion.policy_version == head.policy_version,
                )
            )
            if (
                policy is None
                or policy.policy_sha256 != head.policy_sha256
                or _policy_row_digest(policy) != head.policy_sha256
            ):
                raise StrategyTargetApprovalError("APPROVAL_POLICY_STALE")

            membership_version = target["membership_version"]
            membership_sha256 = target["membership_sha256"]
            if membership_version is not None:
                portfolio_ref = wire.get("portfolio_ref")
                if type(portfolio_ref) is not str or not portfolio_ref:
                    raise StrategyTargetApprovalError("APPROVAL_POLICY_STALE")
                membership = await db.scalar(
                    select(PortfolioCompositionVersion).where(
                        PortfolioCompositionVersion.owner_subject == owner_subject,
                        PortfolioCompositionVersion.portfolio_ref == portfolio_ref,
                        PortfolioCompositionVersion.membership_version == membership_version,
                    )
                )
                latest_membership_version = await db.scalar(
                    select(func.max(PortfolioCompositionVersion.membership_version)).where(
                        PortfolioCompositionVersion.owner_subject == owner_subject,
                        PortfolioCompositionVersion.portfolio_ref == portfolio_ref,
                    )
                )
                if (
                    membership is None
                    or latest_membership_version != membership_version
                    or membership.membership_sha256 != membership_sha256
                    or portfolio_membership_sha256(membership) != membership_sha256
                ):
                    raise StrategyTargetApprovalError("APPROVAL_POLICY_STALE")
            elif membership_sha256 is not None:
                raise StrategyTargetApprovalError("APPROVAL_POLICY_STALE")

            return ApprovedTargetCurrentStateV1(
                target_ref=approval.target_ref,
                target_version=approval.target_version,
                strategy_version=version.version_number,
                membership_version=membership_version,
                membership_sha256=membership_sha256,
                policy_ref=policy.policy_ref,
                policy_version=policy.policy_version,
                policy_sha256=policy.policy_sha256,
                strategy_version_source_id=version.id,
                strategy_version_branch=version.branch,
                strategy_version_sha256=approval.strategy_version_sha256,
            )
        except StrategyTargetApprovalError:
            raise
        except SQLAlchemyError:
            raise StrategyTargetApprovalError("APPROVAL_STORE_UNAVAILABLE", ambiguous=True) from None


def validate_target_against_policy(
    target: Mapping[str, object], policy: Mapping[str, object]
) -> dict[str, object]:
    """Fail closed when an order target exceeds the published AFI policy."""

    normalized_policy = _validate_policy(policy)
    instrument = target.get("instrument")
    if instrument not in normalized_policy["allowed_instruments"]:
        raise StrategyTargetApprovalError("APPROVAL_POLICY_STALE")
    for target_key, policy_key in (
        ("side", "allowed_sides"),
        ("position_effect", "allowed_position_effects"),
        ("order_type", "allowed_order_types"),
        ("time_in_force", "allowed_time_in_force"),
    ):
        if target.get(target_key) not in normalized_policy[policy_key]:
            raise StrategyTargetApprovalError("APPROVAL_POLICY_STALE")
    policy_limits = normalized_policy["limits"]
    target_limits = target.get("limits")
    if not isinstance(policy_limits, dict) or not isinstance(target_limits, Mapping):
        raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID")
    quantity = _as_decimal(target.get("quantity"))
    max_quantity = _as_decimal(policy_limits["max_quantity"])
    target_max_quantity = _as_decimal(target_limits.get("max_quantity"))
    if quantity > max_quantity or target_max_quantity > max_quantity:
        raise StrategyTargetApprovalError("APPROVAL_POLICY_STALE")

    for field in ("max_notional", "min_price", "max_price"):
        policy_value = policy_limits[field]
        target_value = target_limits.get(field)
        if policy_value is None:
            continue
        if target_value is None:
            raise StrategyTargetApprovalError("APPROVAL_POLICY_STALE")
        policy_bound = _as_decimal(policy_value)
        target_bound = _as_decimal(target_value)
        if field == "min_price":
            if target_bound < policy_bound:
                raise StrategyTargetApprovalError("APPROVAL_POLICY_STALE")
        elif target_bound > policy_bound:
            raise StrategyTargetApprovalError("APPROVAL_POLICY_STALE")

    order_type = target.get("order_type")
    price_value = target.get("price")
    policy_max_notional = policy_limits["max_notional"]
    if order_type == "MARKET":
        if policy_max_notional is not None or target_limits.get("max_notional") is not None:
            raise StrategyTargetApprovalError("APPROVAL_POLICY_STALE")
    elif order_type == "LIMIT":
        price = _as_decimal(price_value)
        target_min_price = target_limits.get("min_price")
        target_max_price = target_limits.get("max_price")
        if target_min_price is not None and price < _as_decimal(target_min_price):
            raise StrategyTargetApprovalError("APPROVAL_POLICY_STALE")
        if target_max_price is not None and price > _as_decimal(target_max_price):
            raise StrategyTargetApprovalError("APPROVAL_POLICY_STALE")
        target_max_notional = target_limits.get("max_notional")
        if target_max_notional is not None and quantity * price > _as_decimal(target_max_notional):
            raise StrategyTargetApprovalError("APPROVAL_POLICY_STALE")
        if policy_limits["min_price"] is not None and price < _as_decimal(policy_limits["min_price"]):
            raise StrategyTargetApprovalError("APPROVAL_POLICY_STALE")
        if policy_limits["max_price"] is not None and price > _as_decimal(policy_limits["max_price"]):
            raise StrategyTargetApprovalError("APPROVAL_POLICY_STALE")
        if policy_max_notional is not None and quantity * price > _as_decimal(policy_max_notional):
            raise StrategyTargetApprovalError("APPROVAL_POLICY_STALE")
    else:
        raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID")
    return normalized_policy


async def approve_strategy_order_target(
    db: AsyncSession,
    *,
    target: Mapping[str, object],
    owner_subject: str,
    expected_scope_ref: str,
    target_identity: object,
    target_wire_scope: object,
    approved_by_subject: str,
    approved_by_principal_ref: str,
    approved_by_actor_ref: str,
    approved_by_delegate_ref: str | None,
    approved_at_ns: int,
    expires_at_ns: int,
) -> StrategyTargetApproval:
    """Create one target decision from locked, current AFI-owned source facts.

    The HTTP composition must enforce the dedicated trade-target approval
    permission and construct identity/scope from trusted server bindings.
    Request data supplies only the order terms and version selectors.
    """

    try:
        if not db.in_transaction():
            await db.begin()
        await lock_strategy_approval_authority_epoch(db, owner_subject)
        normalized = _validate_target(target)
        if normalized["owner_subject"] != owner_subject:
            raise StrategyTargetApprovalError("APPROVAL_OWNER_BINDING_MISMATCH")
        if normalized["scope_ref"] != expected_scope_ref:
            raise StrategyTargetApprovalError("APPROVAL_SCOPE_MISMATCH")
        if (
            normalized["principal_ref"] != _identity_field(target_identity, "principal_ref")
            or normalized["actor_ref"] != _identity_field(target_identity, "actor_ref")
            or _delegate_storage_value(normalized["delegate_ref"])
            != _delegate_storage_value(_identity_field(target_identity, "delegate_ref"))
            or _identity_role(target_identity) != "application_client"
            or _scope_payload(target_wire_scope) != normalized["wire_scope"]
        ):
            raise StrategyTargetApprovalError("APPROVAL_IDENTITY_MISMATCH")
        scope = normalized["wire_scope"]
        if not isinstance(scope, dict):
            raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID")
        strategy_ref = scope["strategy_ref"]
        strategy = await db.get(Strategy, strategy_ref)
        if strategy is None or strategy.user_id != owner_subject:
            raise StrategyTargetApprovalError("APPROVAL_OWNER_BINDING_MISMATCH")

        version_result = await db.execute(
            select(StrategyVersion).where(
                StrategyVersion.strategy_id == strategy.id,
                StrategyVersion.version_number == normalized["strategy_version"],
            )
        )
        versions = list(version_result.scalars().all())
        if len(versions) != 1:
            raise StrategyTargetApprovalError("APPROVAL_POLICY_STALE")
        version = versions[0]
        if (
            version.status != VersionStatus.STABLE.value
            or version.is_active is not True
        ):
            raise StrategyTargetApprovalError("APPROVAL_POLICY_STALE")
        branch_result = await db.execute(
            select(VersionBranch).where(
                VersionBranch.strategy_id == strategy.id,
                VersionBranch.branch_name == version.branch,
            )
        )
        branches = list(branch_result.scalars().all())
        if len(branches) != 1 or branches[0].last_version_id != version.id:
            raise StrategyTargetApprovalError("APPROVAL_POLICY_STALE")

        policy_head = await db.get(StrategyOrderApprovalPolicyHead, owner_subject)
        if (
            policy_head is None
            or policy_head.policy_ref != normalized["policy_ref"]
            or policy_head.policy_version != normalized["policy_version"]
            or policy_head.policy_sha256 != normalized["policy_sha256"]
        ):
            raise StrategyTargetApprovalError("APPROVAL_POLICY_STALE")
        policy = await db.scalar(
            select(StrategyOrderApprovalPolicyVersion).where(
                StrategyOrderApprovalPolicyVersion.owner_subject == owner_subject,
                StrategyOrderApprovalPolicyVersion.policy_ref == policy_head.policy_ref,
                StrategyOrderApprovalPolicyVersion.policy_version == policy_head.policy_version,
            )
        )
        if (
            policy is None
            or policy.policy_sha256 != policy_head.policy_sha256
            or _policy_row_digest(policy) != policy_head.policy_sha256
        ):
            raise StrategyTargetApprovalError("APPROVAL_POLICY_STALE")
        policy_value = json.loads(policy.canonical_policy_json)
        validate_target_against_policy(normalized, policy_value)

        membership_version = normalized["membership_version"]
        membership_digest = normalized["membership_sha256"]
        if membership_version is not None:
            portfolio_ref = scope["portfolio_ref"]
            if type(portfolio_ref) is not str:
                raise StrategyTargetApprovalError("APPROVAL_POLICY_STALE")
            membership = await db.scalar(
                select(PortfolioCompositionVersion).where(
                    PortfolioCompositionVersion.owner_subject == owner_subject,
                    PortfolioCompositionVersion.portfolio_ref == portfolio_ref,
                    PortfolioCompositionVersion.membership_version == membership_version,
                )
            )
            latest_membership_version = await db.scalar(
                select(func.max(PortfolioCompositionVersion.membership_version)).where(
                    PortfolioCompositionVersion.owner_subject == owner_subject,
                    PortfolioCompositionVersion.portfolio_ref == portfolio_ref,
                )
            )
            if (
                membership is None
                or latest_membership_version != membership_version
                or membership.membership_sha256 != membership_digest
                or portfolio_membership_sha256(membership) != membership_digest
            ):
                raise StrategyTargetApprovalError("APPROVAL_POLICY_STALE")

        target_digest = canonical_target_sha256(normalized)
        approval = await create_approved_order_target(
            db,
            target=normalized,
            target_sha256=target_digest,
            approval_ref=None,
            approval_version=1,
            owner_subject=owner_subject,
            expected_scope_ref=expected_scope_ref,
            target_identity=target_identity,
            target_wire_scope=target_wire_scope,
            approved_by_subject=approved_by_subject,
            approved_by_principal_ref=approved_by_principal_ref,
            approved_by_actor_ref=approved_by_actor_ref,
            approved_by_delegate_ref=approved_by_delegate_ref,
            approved_at_ns=approved_at_ns,
            expires_at_ns=expires_at_ns,
            strategy_version_source_id=version.id,
            strategy_version_branch=version.branch,
            strategy_version_sha256=strategy_version_content_sha256(version),
            commit=False,
        )
        await db.commit()
        return approval
    except StrategyTargetApprovalError:
        if db.in_transaction():
            await db.rollback()
        raise
    except SQLAlchemyError:
        if db.in_transaction():
            await db.rollback()
        raise StrategyTargetApprovalError("APPROVAL_STORE_UNAVAILABLE", ambiguous=True) from None
    except BaseException:
        if db.in_transaction():
            await db.rollback()
        raise


def _policy_row_digest(row: StrategyOrderApprovalPolicyVersion) -> str:
    try:
        parsed = json.loads(row.canonical_policy_json)
        canonical = canonical_policy_json(parsed)
    except (TypeError, ValueError, StrategyTargetApprovalError):
        raise StrategyTargetApprovalError("APPROVAL_POLICY_STALE") from None
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if canonical != row.canonical_policy_json or digest != row.policy_sha256:
        raise StrategyTargetApprovalError("APPROVAL_POLICY_STALE")
    return digest


def _validate_policy(policy: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(policy, Mapping) or set(policy) != _POLICY_KEYS:
        raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID")
    if policy.get("schema_id") != "afi.strategy_order_approval_policy" or type(
        policy.get("schema_version")
    ) is not int or policy.get("schema_version") != 1:
        raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID")
    instruments = policy.get("allowed_instruments")
    if (
        not isinstance(instruments, list)
        or not instruments
        or any(type(value) is not str or not _INSTRUMENT_RE.fullmatch(value) for value in instruments)
        or len(set(instruments)) != len(instruments)
    ):
        raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID")
    result: dict[str, object] = {
        "schema_id": "afi.strategy_order_approval_policy",
        "schema_version": 1,
        "allowed_instruments": sorted(instruments),
    }
    for name, choices in _ENUMS.items():
        values = policy.get(name)
        if (
            not isinstance(values, list)
            or not values
            or any(type(value) is not str or value not in choices for value in values)
            or len(set(values)) != len(values)
        ):
            raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID")
        result[name] = sorted(values)
    limits = policy.get("limits")
    if not isinstance(limits, Mapping) or set(limits) != _LIMIT_KEYS:
        raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID")
    max_quantity = _decimal_text(limits.get("max_quantity"), positive=True)
    normalized_limits: dict[str, object] = {"max_quantity": max_quantity}
    for name in ("max_notional", "min_price", "max_price"):
        value = limits.get(name)
        normalized_limits[name] = None if value is None else _decimal_text(value, positive=True)
    if (
        normalized_limits["min_price"] is not None
        and normalized_limits["max_price"] is not None
        and _as_decimal(normalized_limits["min_price"])
        > _as_decimal(normalized_limits["max_price"])
    ):
        raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID")
    result["limits"] = normalized_limits
    return result


def _decimal_text(value: object, *, positive: bool) -> str:
    if type(value) is not str or not _DECIMAL_RE.fullmatch(value):
        raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID")
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID") from None
    if not number.is_finite() or (positive and number <= 0):
        raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID")
    return value


def _as_decimal(value: object) -> Decimal:
    try:
        if type(value) is not str or not _DECIMAL_RE.fullmatch(value):
            raise InvalidOperation
        result = Decimal(value)
        if not result.is_finite() or result <= 0:
            raise InvalidOperation
        return result
    except (InvalidOperation, TypeError):
        raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID") from None


def _required_identifier(value: object, max_length: int) -> None:
    if type(value) is not str or not value or len(value) > max_length:
        raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID")


def _wire_scope_mapping(value: object) -> dict[str, object]:
    if isinstance(value, Mapping):
        result = dict(value)
    else:
        payload = getattr(value, "model_dump", None)
        if callable(payload):
            dumped = payload(mode="json")
            if isinstance(dumped, dict):
                result = dumped
            else:
                result = {}
        else:
            names = (
                "execution_domain_ref",
                "account_ref",
                "account_refs",
                "strategy_ref",
                "run_id",
                "manual_book_ref",
                "portfolio_ref",
                "group_id",
                "leg_id",
            )
            result = {name: getattr(value, name, None) for name in names}
    account_refs = result.get("account_refs")
    if isinstance(account_refs, (list, tuple)):
        result["account_refs"] = list(account_refs)
    return result
