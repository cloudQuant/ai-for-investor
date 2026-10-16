"""Durable store boundary for approved single-order strategy targets.

The caller of these functions must already have passed the code-owned
authenticated identity/scope-to-owner binding.  This module never derives an
owner from an approval reference or a client field.  Execution's journal, not
this store, remains authoritative for admission, provider dispatch, and order
state. Target creation remains application-client-only. The trusted Execution
owner may reserve, resolve, and consume an existing target, but a SERVICE
identity is limited to CLOSE/reduce-only targets.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any, Protocol

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.strategy_target_approval import (
    StrategyTargetApproval,
    StrategyTargetApprovalEvent,
)

_TARGET_KEYS = frozenset(
    {
        "schema_id",
        "schema_version",
        "target_ref",
        "target_version",
        "owner_subject",
        "principal_ref",
        "actor_ref",
        "delegate_ref",
        "scope_ref",
        "wire_scope",
        "strategy_version",
        "membership_version",
        "membership_sha256",
        "instrument",
        "metadata_version",
        "side",
        "position_effect",
        "order_type",
        "quantity",
        "price",
        "time_in_force",
        "reduce_only",
        "deadline_ns",
        "limits",
        "policy_ref",
        "policy_version",
        "policy_sha256",
    }
)
_WIRE_SCOPE_KEYS = frozenset(
    {
        "execution_domain_ref",
        "account_ref",
        "account_refs",
        "strategy_ref",
        "run_id",
        "manual_book_ref",
        "portfolio_ref",
        "group_id",
        "leg_id",
    }
)
_LIMIT_KEYS = frozenset({"max_quantity", "max_notional", "min_price", "max_price"})
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_INSTRUMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,191}$")
_DECIMAL = re.compile(r"^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")
_DECIMAL_TEXT_MAX = 128
_REASON_CODE = re.compile(r"^[a-z][a-z0-9_]{0,127}$")
_DETERMINISTIC_CODES = frozenset(
    {
        "APPROVAL_NOT_FOUND",
        "APPROVAL_OWNER_BINDING_MISMATCH",
        "APPROVAL_IDENTITY_MISMATCH",
        "APPROVAL_SCOPE_MISMATCH",
        "APPROVAL_NOT_APPROVED",
        "APPROVAL_REVOKED",
        "APPROVAL_EXPIRED",
        "APPROVAL_VERSION_MISMATCH",
        "APPROVAL_TARGET_DIGEST_MISMATCH",
        "APPROVAL_TARGET_INVALID",
        "APPROVAL_POLICY_STALE",
        "APPROVAL_OPERATION_CONFLICT",
        "APPROVAL_CONSUMED_CONFLICT",
    }
)


class StrategyTargetApprovalError(RuntimeError):
    """Finite authority failure; SQL/store failures are marked ambiguous."""

    def __init__(self, code: str, *, ambiguous: bool = False) -> None:
        if code not in _DETERMINISTIC_CODES and code != "APPROVAL_STORE_UNAVAILABLE":
            code = "APPROVAL_TARGET_INVALID"
        self.code = code
        self.ambiguous = ambiguous
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ApprovedTargetOperationClaim:
    approval_ref: str
    approval_version: int
    target_sha256: str
    intent_id: str
    operation_request_sha256: str
    created: bool
    record_version: int


@dataclass(frozen=True, slots=True)
class ApprovedTargetCurrentStateV1:
    """Trusted current target/policy/membership values checked before consume."""

    target_ref: str
    target_version: int
    strategy_version: int
    membership_version: int | None
    membership_sha256: str | None
    policy_ref: str
    policy_version: int
    policy_sha256: str
    strategy_version_source_id: str
    strategy_version_branch: str
    strategy_version_sha256: str


class ApprovedTargetCurrentStateProvider(Protocol):
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
    ) -> ApprovedTargetCurrentStateV1: ...


def canonical_target_json(target: Mapping[str, object]) -> str:
    """Validate and encode the exact approved-target v1 JSON representation."""

    normalized = _validate_target(target)
    return json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def canonical_target_sha256(target: Mapping[str, object]) -> str:
    """Return the frozen SDK-compatible digest of one target payload."""

    return hashlib.sha256(canonical_target_json(target).encode("utf-8")).hexdigest()


def operation_key_sha256(value: str) -> str:
    if type(value) is not str or not value or len(value) > 256:
        raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID") from None
    return hashlib.sha256(encoded).hexdigest()


async def create_approved_order_target(
    db: AsyncSession,
    *,
    target: Mapping[str, object],
    target_sha256: str,
    approval_ref: str | None,
    approval_version: int,
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
    strategy_version_source_id: str | None = None,
    strategy_version_branch: str | None = None,
    strategy_version_sha256: str | None = None,
    commit: bool = True,
) -> StrategyTargetApproval:
    """Persist an already-authorized decision and its immutable target.

    Authentication and the trade-target approval permission are enforced by
    the route/composition caller.  The caller supplies only server-derived
    decision identity; a request's ``approved`` flag is never accepted here.
    """

    normalized = _validate_target(target)
    calculated_digest = canonical_target_sha256(normalized)
    if not _valid_hash(target_sha256) or calculated_digest != target_sha256:
        raise StrategyTargetApprovalError("APPROVAL_TARGET_DIGEST_MISMATCH")
    _required_text(owner_subject, "owner_subject", 256)
    _required_identifier(expected_scope_ref, "expected_scope_ref")
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
    _required_text(approved_by_subject, "approved_by_subject", 256)
    _required_identifier(approved_by_principal_ref, "approved_by_principal_ref")
    _required_identifier(approved_by_actor_ref, "approved_by_actor_ref")
    _delegate_storage_value(approved_by_delegate_ref)
    if type(approved_at_ns) is not int or approved_at_ns <= 0:
        raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID")
    if type(expires_at_ns) is not int or expires_at_ns <= approved_at_ns:
        raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID")
    if type(approval_version) is not int or approval_version <= 0:
        raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID")
    if strategy_version_source_id is not None:
        _required_identifier(strategy_version_source_id, "strategy_version_source_id")
        _required_identifier(strategy_version_branch, "strategy_version_branch")
        if not _valid_hash(strategy_version_sha256):
            raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID")
    elif strategy_version_branch is not None or strategy_version_sha256 is not None:
        raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID")
    from app.services.strategy_approval_authority import (
        lock_strategy_approval_authority_epoch,
    )

    await lock_strategy_approval_authority_epoch(db, owner_subject)
    if approval_ref is None:
        approval_ref = uuid.uuid4().hex
    else:
        _required_identifier(approval_ref, "approval_ref")

    wire_scope = normalized["wire_scope"]
    assert isinstance(wire_scope, dict)
    membership_version = normalized["membership_version"]
    membership_sha256 = normalized["membership_sha256"]
    row = StrategyTargetApproval(
        approval_ref=approval_ref,
        approval_version=approval_version,
        record_version=1,
        state="APPROVED",
        owner_subject=owner_subject,
        principal_ref=normalized["principal_ref"],
        actor_ref=normalized["actor_ref"],
        delegate_ref=_delegate_storage_value(normalized["delegate_ref"]),
        scope_ref=normalized["scope_ref"],
        execution_domain_ref=wire_scope["execution_domain_ref"],
        account_ref=wire_scope["account_ref"],
        strategy_ref=wire_scope["strategy_ref"],
        strategy_version=normalized["strategy_version"],
        strategy_version_source_id=strategy_version_source_id,
        strategy_version_branch=strategy_version_branch,
        strategy_version_sha256=strategy_version_sha256,
        membership_version=membership_version,
        membership_sha256=membership_sha256,
        target_ref=normalized["target_ref"],
        target_version=normalized["target_version"],
        target_sha256=calculated_digest,
        canonical_target_json=json.dumps(
            normalized,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ),
        policy_ref=normalized["policy_ref"],
        policy_version=normalized["policy_version"],
        policy_sha256=normalized["policy_sha256"],
        approved_by_subject=approved_by_subject,
        approved_by_principal_ref=approved_by_principal_ref,
        approved_by_actor_ref=approved_by_actor_ref,
        approved_by_delegate_ref=_delegate_storage_value(approved_by_delegate_ref),
        approved_at_ns=approved_at_ns,
        expires_at_ns=expires_at_ns,
    )
    db.add(row)
    event = _event(
        row,
        event_type="APPROVED",
        actor_subject=approved_by_subject,
        principal_ref=approved_by_principal_ref,
        actor_ref=approved_by_actor_ref,
        delegate_ref=approved_by_delegate_ref,
        occurred_at_ns=approved_at_ns,
    )
    db.add(event)
    try:
        if commit:
            await db.commit()
        else:
            await db.flush()
        return row
    except IntegrityError:
        await db.rollback()
        raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID") from None
    except SQLAlchemyError:
        await db.rollback()
        raise StrategyTargetApprovalError("APPROVAL_STORE_UNAVAILABLE", ambiguous=True) from None


async def reserve_approved_target_operation(
    db: AsyncSession,
    *,
    approval_ref: str,
    approval_version: int,
    target_sha256: str,
    operation_key: str,
    intent_id: str,
    owner_subject: str,
    principal_ref: str,
    expected_scope_ref: str,
    identity: object,
    wire_scope: object,
    now_ns: int | None = None,
) -> ApprovedTargetOperationClaim:
    """Atomically pin an operation key to its caller-supplied stable intent ID."""

    from app.services.strategy_approval_authority import (
        lock_strategy_approval_authority_epoch,
    )

    await lock_strategy_approval_authority_epoch(db, owner_subject)

    row = await _load_bound_approval(
        db,
        approval_ref=approval_ref,
        approval_version=approval_version,
        target_sha256=target_sha256,
        owner_subject=owner_subject,
        principal_ref=principal_ref,
        expected_scope_ref=expected_scope_ref,
        identity=identity,
        wire_scope=wire_scope,
    )
    key_digest = operation_key_sha256(operation_key)
    _required_identifier(intent_id, "intent_id")
    request_digest = _operation_request_sha256(row, intent_id)
    if row.operation_key_sha256 is not None:
        if (
            row.operation_key_sha256 != key_digest
            or row.operation_request_sha256 != request_digest
            or row.intent_id != intent_id
        ):
            raise StrategyTargetApprovalError("APPROVAL_OPERATION_CONFLICT")
        return ApprovedTargetOperationClaim(
            row.approval_ref,
            row.approval_version,
            row.target_sha256,
            row.intent_id,
            row.operation_request_sha256,
            False,
            row.record_version,
        )

    current_ns = _now_ns(now_ns)
    if row.state == "REVOKED":
        raise StrategyTargetApprovalError("APPROVAL_REVOKED")
    if row.state != "APPROVED":
        raise StrategyTargetApprovalError("APPROVAL_OPERATION_CONFLICT")
    if row.expires_at_ns <= current_ns:
        raise StrategyTargetApprovalError("APPROVAL_EXPIRED")

    new_record_version = row.record_version + 1
    try:
        result = await _cas_update(
            db,
            row,
            {
                "operation_key_sha256": key_digest,
                "operation_request_sha256": request_digest,
                "intent_id": intent_id,
                "operation_reserved_at_ns": current_ns,
                "record_version": new_record_version,
            },
            rethrow_integrity=True,
        )
    except IntegrityError:
        conflict = await _find_operation_key(
            db,
            owner_subject=owner_subject,
            principal_ref=principal_ref,
            actor_ref=_identity_field(identity, "actor_ref"),
            delegate_ref=_delegate_storage_value(_identity_field(identity, "delegate_ref")),
            operation_key_hash=key_digest,
        )
        if conflict is None:
            raise StrategyTargetApprovalError("APPROVAL_STORE_UNAVAILABLE", ambiguous=True) from None
        if (
            conflict.approval_ref == approval_ref
            and conflict.operation_request_sha256 == request_digest
            and conflict.intent_id == intent_id
        ):
            return ApprovedTargetOperationClaim(
                conflict.approval_ref,
                conflict.approval_version,
                conflict.target_sha256,
                conflict.intent_id,
                conflict.operation_request_sha256,
                False,
                conflict.record_version,
            )
        raise StrategyTargetApprovalError("APPROVAL_OPERATION_CONFLICT") from None
    if not result:
        await db.rollback()
        refreshed = await _load_bound_approval(
            db,
            approval_ref=approval_ref,
            approval_version=approval_version,
            target_sha256=target_sha256,
            owner_subject=owner_subject,
            principal_ref=principal_ref,
            expected_scope_ref=expected_scope_ref,
            identity=identity,
            wire_scope=wire_scope,
        )
        if (
            refreshed.operation_key_sha256 == key_digest
            and refreshed.operation_request_sha256 == request_digest
            and refreshed.intent_id == intent_id
        ):
            return ApprovedTargetOperationClaim(
                refreshed.approval_ref,
                refreshed.approval_version,
                refreshed.target_sha256,
                refreshed.intent_id,
                refreshed.operation_request_sha256,
                False,
                refreshed.record_version,
            )
        if refreshed.operation_key_sha256 is not None:
            raise StrategyTargetApprovalError("APPROVAL_OPERATION_CONFLICT")
        raise StrategyTargetApprovalError("APPROVAL_STORE_UNAVAILABLE", ambiguous=True)

    event = _event(
        row,
        event_type="OPERATION_RESERVED",
        actor_subject=owner_subject,
        principal_ref=principal_ref,
        actor_ref=_identity_field(identity, "actor_ref"),
        delegate_ref=_identity_field(identity, "delegate_ref"),
        occurred_at_ns=current_ns,
        operation_key_sha256=key_digest,
        intent_id=intent_id,
    )
    db.add(event)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        conflict = await _find_operation_key(
            db,
            owner_subject=owner_subject,
            principal_ref=principal_ref,
            actor_ref=_identity_field(identity, "actor_ref"),
            delegate_ref=_delegate_storage_value(_identity_field(identity, "delegate_ref")),
            operation_key_hash=key_digest,
        )
        if conflict is not None:
            if (
                conflict.approval_ref == approval_ref
                and conflict.operation_request_sha256 == request_digest
                and conflict.intent_id == intent_id
            ):
                return ApprovedTargetOperationClaim(
                    conflict.approval_ref,
                    conflict.approval_version,
                    conflict.target_sha256,
                    conflict.intent_id,
                    conflict.operation_request_sha256,
                    False,
                    conflict.record_version,
                )
            raise StrategyTargetApprovalError("APPROVAL_OPERATION_CONFLICT")
        raise StrategyTargetApprovalError("APPROVAL_STORE_UNAVAILABLE", ambiguous=True) from None
    except SQLAlchemyError:
        await db.rollback()
        raise StrategyTargetApprovalError("APPROVAL_STORE_UNAVAILABLE", ambiguous=True) from None
    return ApprovedTargetOperationClaim(
        approval_ref,
        approval_version,
        target_sha256,
        intent_id,
        request_digest,
        True,
        new_record_version,
    )


async def resolve_approved_target_v1(
    db: AsyncSession,
    approval_ref: str,
    approval_version: int,
    target_sha256: str,
    *,
    operation_key: str,
    intent_id: str,
    owner_subject: str,
    principal_ref: str,
    expected_scope_ref: str,
    identity: object,
    wire_scope: object,
) -> dict[str, object]:
    """Return target data for the exact reserved intent and trusted identity.

    This is reconstruction data, not permission to dispatch.  Execution must
    call ``consume_approved_target_v1`` at its pre-dispatch gate; that method
    alone enforces expiry, revocation, and the one-use consume transition.
    """

    row = await _load_bound_approval(
        db,
        approval_ref=approval_ref,
        approval_version=approval_version,
        target_sha256=target_sha256,
        owner_subject=owner_subject,
        principal_ref=principal_ref,
        expected_scope_ref=expected_scope_ref,
        identity=identity,
        wire_scope=wire_scope,
    )
    _require_reserved_operation_binding(row, operation_key, intent_id)
    return _target_from_row(row)


async def consume_approved_target_v1(
    db: AsyncSession,
    approval_ref: str,
    approval_version: int,
    target_sha256: str,
    *,
    operation_key: str,
    intent_id: str,
    intent_sha256: str,
    owner_subject: str,
    principal_ref: str,
    expected_scope_ref: str,
    identity: object,
    wire_scope: object,
    current_state_provider: ApprovedTargetCurrentStateProvider,
    now_ns: int | None = None,
) -> dict[str, object]:
    from app.services.strategy_approval_authority import (
        lock_strategy_approval_authority_epoch,
    )

    if not db.in_transaction():
        try:
            await db.begin()
        except SQLAlchemyError:
            raise StrategyTargetApprovalError("APPROVAL_STORE_UNAVAILABLE", ambiguous=True) from None
    try:
        await lock_strategy_approval_authority_epoch(db, owner_subject)
        result = await _consume_approved_target_v1_in_transaction(
            db,
            approval_ref,
            approval_version,
            target_sha256,
            operation_key=operation_key,
            intent_id=intent_id,
            intent_sha256=intent_sha256,
            owner_subject=owner_subject,
            principal_ref=principal_ref,
            expected_scope_ref=expected_scope_ref,
            identity=identity,
            wire_scope=wire_scope,
            current_state_provider=current_state_provider,
            now_ns=now_ns,
        )
    except BaseException:
        if db.in_transaction():
            try:
                await db.rollback()
            except Exception:
                pass
        raise
    if db.in_transaction():
        try:
            await db.rollback()
        except SQLAlchemyError:
            raise StrategyTargetApprovalError("APPROVAL_STORE_UNAVAILABLE", ambiguous=True) from None
    return result


async def _consume_approved_target_v1_in_transaction(
    db: AsyncSession,
    approval_ref: str,
    approval_version: int,
    target_sha256: str,
    *,
    operation_key: str,
    intent_id: str,
    intent_sha256: str,
    owner_subject: str,
    principal_ref: str,
    expected_scope_ref: str,
    identity: object,
    wire_scope: object,
    current_state_provider: ApprovedTargetCurrentStateProvider,
    now_ns: int | None,
) -> dict[str, object]:
    """Linearize revocation against first consume and return a finite receipt.

    ``CONSUMED_NEW`` records the AFI authorization fact only.  A repeated exact
    consume returns ``ALREADY_CONSUMED`` for reconciliation; that disposition
    must never authorize a new provider attempt.  Execution's durable
    DISPATCHING fence and journal determine whether it may call a provider.
    """

    if not _valid_hash(intent_sha256):
        raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID")
    row = await _load_bound_approval(
        db,
        approval_ref=approval_ref,
        approval_version=approval_version,
        target_sha256=target_sha256,
        owner_subject=owner_subject,
        principal_ref=principal_ref,
        expected_scope_ref=expected_scope_ref,
        identity=identity,
        wire_scope=wire_scope,
    )
    _require_reserved_operation_binding(row, operation_key, intent_id)
    if row.state == "CONSUMED":
        if row.consumed_intent_sha256 != intent_sha256:
            raise StrategyTargetApprovalError("APPROVAL_CONSUMED_CONFLICT")
        return _consumption_receipt(row, "ALREADY_CONSUMED")
    if row.state == "REVOKED":
        raise StrategyTargetApprovalError("APPROVAL_REVOKED")
    if row.state != "APPROVED":
        raise StrategyTargetApprovalError("APPROVAL_NOT_APPROVED")
    if row.expires_at_ns <= _now_ns(now_ns):
        raise StrategyTargetApprovalError("APPROVAL_EXPIRED")
    if row.operation_key_sha256 is None or row.operation_request_sha256 is None:
        raise StrategyTargetApprovalError("APPROVAL_OPERATION_CONFLICT")

    target = _target_from_row(row)
    await _require_current_approved_target_state(
        current_state_provider,
        db=db,
        approval_ref=approval_ref,
        approval_version=approval_version,
        target_sha256=target_sha256,
        target=target,
        owner_subject=owner_subject,
        principal_ref=principal_ref,
        expected_scope_ref=expected_scope_ref,
        identity=identity,
        wire_scope=wire_scope,
        strategy_version_source_id=row.strategy_version_source_id,
        strategy_version_branch=row.strategy_version_branch,
        strategy_version_sha256=row.strategy_version_sha256,
    )

    current_ns = _now_ns(now_ns)
    consumption_ref = uuid.uuid4().hex
    consumed_record_version = row.record_version + 1
    result = await _cas_update(
        db,
        row,
        {
            "state": "CONSUMED",
            "consumption_ref": consumption_ref,
            "consumed_intent_sha256": intent_sha256,
            "consumed_at_ns": current_ns,
            "consumed_record_version": consumed_record_version,
            "record_version": consumed_record_version,
        },
        state="APPROVED",
    )
    if not result:
        await db.rollback()
        refreshed = await _load_bound_approval(
            db,
            approval_ref=approval_ref,
            approval_version=approval_version,
            target_sha256=target_sha256,
            owner_subject=owner_subject,
            principal_ref=principal_ref,
            expected_scope_ref=expected_scope_ref,
            identity=identity,
            wire_scope=wire_scope,
        )
        if refreshed.state == "CONSUMED":
            if (
                refreshed.intent_id == intent_id
                and refreshed.consumed_intent_sha256 == intent_sha256
            ):
                return _consumption_receipt(refreshed, "ALREADY_CONSUMED")
            raise StrategyTargetApprovalError("APPROVAL_CONSUMED_CONFLICT")
        if refreshed.state == "REVOKED":
            raise StrategyTargetApprovalError("APPROVAL_REVOKED")
        raise StrategyTargetApprovalError("APPROVAL_STORE_UNAVAILABLE", ambiguous=True)

    event = _event(
        row,
        event_type="CONSUMED",
        actor_subject=owner_subject,
        principal_ref=principal_ref,
        actor_ref=_identity_field(identity, "actor_ref"),
        delegate_ref=_identity_field(identity, "delegate_ref"),
        occurred_at_ns=current_ns,
        operation_key_sha256=row.operation_key_sha256,
        intent_id=intent_id,
        intent_sha256=intent_sha256,
        consumption_ref=consumption_ref,
    )
    db.add(event)
    try:
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        raise StrategyTargetApprovalError("APPROVAL_STORE_UNAVAILABLE", ambiguous=True) from None
    return _consumption_receipt(row, "CONSUMED_NEW")


async def revoke_approved_order_target(
    db: AsyncSession,
    *,
    approval_ref: str,
    approval_version: int,
    owner_subject: str,
    revoker_subject: str,
    revoker_principal_ref: str,
    revoker_actor_ref: str,
    revoker_delegate_ref: str | None,
    reason_code: str,
    revoked_at_ns: int | None = None,
) -> int:
    """Revoke an unconsumed target using a record-version compare-and-swap.

    The route must enforce the current trade-approval permission and derive
    revoker identity from authentication; free-form caller authority is not
    accepted.  This transaction is the race ordering point against consume.
    """

    from app.services.strategy_approval_authority import (
        lock_strategy_approval_authority_epoch,
    )

    _required_text(revoker_subject, "revoker_subject", 256)
    _required_identifier(revoker_principal_ref, "revoker_principal_ref")
    _required_identifier(revoker_actor_ref, "revoker_actor_ref")
    _delegate_storage_value(revoker_delegate_ref)
    if type(reason_code) is not str or not _REASON_CODE.fullmatch(reason_code):
        raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID")
    current_ns = _now_ns(revoked_at_ns)
    await lock_strategy_approval_authority_epoch(db, owner_subject)
    row = await _load_for_owner(db, approval_ref, approval_version, owner_subject)
    if row.state == "CONSUMED":
        raise StrategyTargetApprovalError("APPROVAL_CONSUMED_CONFLICT")
    if row.state == "REVOKED":
        if (
            row.revoked_by_subject == revoker_subject
            and row.revoked_by_actor_ref == revoker_actor_ref
            and row.revocation_reason_code == reason_code
        ):
            return row.record_version
        raise StrategyTargetApprovalError("APPROVAL_REVOKED")
    new_record_version = row.record_version + 1
    result = await _cas_update(
        db,
        row,
        {
            "state": "REVOKED",
            "revoked_by_subject": revoker_subject,
            "revoked_by_actor_ref": revoker_actor_ref,
            "revoked_at_ns": current_ns,
            "revocation_reason_code": reason_code,
            "record_version": new_record_version,
        },
        state="APPROVED",
    )
    if not result:
        await db.rollback()
        refreshed = await _load_for_owner(db, approval_ref, approval_version, owner_subject)
        if refreshed.state == "CONSUMED":
            raise StrategyTargetApprovalError("APPROVAL_CONSUMED_CONFLICT")
        if refreshed.state == "REVOKED":
            if (
                refreshed.revoked_by_subject == revoker_subject
                and refreshed.revoked_by_actor_ref == revoker_actor_ref
                and refreshed.revocation_reason_code == reason_code
            ):
                return refreshed.record_version
            raise StrategyTargetApprovalError("APPROVAL_REVOKED")
        raise StrategyTargetApprovalError("APPROVAL_STORE_UNAVAILABLE", ambiguous=True)
    db.add(
        _event(
            row,
            event_type="REVOKED",
            actor_subject=revoker_subject,
            principal_ref=revoker_principal_ref,
            actor_ref=revoker_actor_ref,
            delegate_ref=revoker_delegate_ref,
            occurred_at_ns=current_ns,
            reason_code=reason_code,
        )
    )
    try:
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        raise StrategyTargetApprovalError("APPROVAL_STORE_UNAVAILABLE", ambiguous=True) from None
    return new_record_version


async def _load_bound_approval(
    db: AsyncSession,
    *,
    approval_ref: str,
    approval_version: int,
    target_sha256: str,
    owner_subject: str,
    principal_ref: str,
    expected_scope_ref: str,
    identity: object,
    wire_scope: object,
) -> StrategyTargetApproval:
    row = await _load_by_ref(db, approval_ref)
    if row.owner_subject != owner_subject:
        raise StrategyTargetApprovalError("APPROVAL_OWNER_BINDING_MISMATCH")
    if row.scope_ref != expected_scope_ref:
        raise StrategyTargetApprovalError("APPROVAL_SCOPE_MISMATCH")
    identity_role = _identity_role(identity)
    service_close_use = False
    if identity_role == "service":
        persisted_target = _target_from_row(row)
        service_close_use = (
            persisted_target.get("position_effect") == "CLOSE"
            and persisted_target.get("reduce_only") is True
        )
    if (
        row.principal_ref != principal_ref
        or row.principal_ref != _identity_field(identity, "principal_ref")
        or row.actor_ref != _identity_field(identity, "actor_ref")
        or row.delegate_ref
        != _delegate_storage_value(_identity_field(identity, "delegate_ref"))
        or not (
            identity_role == "application_client"
            or (identity_role == "service" and service_close_use)
        )
    ):
        raise StrategyTargetApprovalError("APPROVAL_IDENTITY_MISMATCH")
    actual_scope = _scope_payload(wire_scope)
    if actual_scope != _target_from_row(row)["wire_scope"]:
        raise StrategyTargetApprovalError("APPROVAL_SCOPE_MISMATCH")
    if type(approval_version) is not int or row.approval_version != approval_version:
        raise StrategyTargetApprovalError("APPROVAL_VERSION_MISMATCH")
    if not _valid_hash(target_sha256) or row.target_sha256 != target_sha256:
        raise StrategyTargetApprovalError("APPROVAL_TARGET_DIGEST_MISMATCH")
    return row


async def _load_for_owner(
    db: AsyncSession, approval_ref: str, approval_version: int, owner_subject: str
) -> StrategyTargetApproval:
    row = await _load_by_ref(db, approval_ref)
    if row.owner_subject != owner_subject:
        raise StrategyTargetApprovalError("APPROVAL_OWNER_BINDING_MISMATCH")
    if type(approval_version) is not int or row.approval_version != approval_version:
        raise StrategyTargetApprovalError("APPROVAL_VERSION_MISMATCH")
    return row


async def _load_by_ref(db: AsyncSession, approval_ref: str) -> StrategyTargetApproval:
    try:
        row = await db.get(StrategyTargetApproval, approval_ref)
    except SQLAlchemyError:
        raise StrategyTargetApprovalError("APPROVAL_STORE_UNAVAILABLE", ambiguous=True) from None
    if row is None:
        raise StrategyTargetApprovalError("APPROVAL_NOT_FOUND")
    _target_from_row(row)
    return row


def _target_from_row(row: StrategyTargetApproval) -> dict[str, object]:
    try:
        target = json.loads(row.canonical_target_json)
        normalized = _validate_target(target)
        canonical = json.dumps(
            normalized,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError, InvalidOperation):
        raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID") from None
    if canonical != row.canonical_target_json or canonical_target_sha256(normalized) != row.target_sha256:
        raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID")
    wire_scope = normalized["wire_scope"]
    assert isinstance(wire_scope, dict)
    if (
        normalized["owner_subject"] != row.owner_subject
        or normalized["principal_ref"] != row.principal_ref
        or normalized["actor_ref"] != row.actor_ref
        or _delegate_storage_value(normalized["delegate_ref"]) != row.delegate_ref
        or normalized["scope_ref"] != row.scope_ref
        or normalized["target_ref"] != row.target_ref
        or normalized["target_version"] != row.target_version
        or normalized["strategy_version"] != row.strategy_version
        or normalized["membership_version"] != row.membership_version
        or normalized["membership_sha256"] != row.membership_sha256
        or normalized["policy_ref"] != row.policy_ref
        or normalized["policy_version"] != row.policy_version
        or normalized["policy_sha256"] != row.policy_sha256
        or wire_scope["execution_domain_ref"] != row.execution_domain_ref
        or wire_scope["account_ref"] != row.account_ref
        or wire_scope["strategy_ref"] != row.strategy_ref
    ):
        raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID")
    return normalized


async def _require_current_approved_target_state(
    provider: ApprovedTargetCurrentStateProvider,
    *,
    db: AsyncSession,
    approval_ref: str,
    approval_version: int,
    target_sha256: str,
    target: Mapping[str, object],
    owner_subject: str,
    principal_ref: str,
    expected_scope_ref: str,
    identity: object,
    wire_scope: object,
    strategy_version_source_id: str | None,
    strategy_version_branch: str | None,
    strategy_version_sha256: str | None,
) -> None:
    """Read trusted current state in the same transaction as the consume CAS."""

    reader = getattr(provider, "read_current_approval_state_v1", None)
    if not callable(reader):
        raise StrategyTargetApprovalError("APPROVAL_POLICY_STALE")
    try:
        current = await reader(
            db,
            approval_ref,
            approval_version,
            target_sha256,
            owner_subject=owner_subject,
            principal_ref=principal_ref,
            expected_scope_ref=expected_scope_ref,
            identity=identity,
            wire_scope=wire_scope,
        )
    except StrategyTargetApprovalError:
        raise
    except Exception:
        raise StrategyTargetApprovalError("APPROVAL_STORE_UNAVAILABLE", ambiguous=True) from None
    if type(current) is not ApprovedTargetCurrentStateV1:
        raise StrategyTargetApprovalError("APPROVAL_POLICY_STALE")
    try:
        _required_identifier(current.target_ref, "current.target_ref")
        _positive_int(current.target_version, "current.target_version")
        _positive_int(current.strategy_version, "current.strategy_version")
        if current.membership_version is None:
            if current.membership_sha256 is not None:
                raise StrategyTargetApprovalError("APPROVAL_POLICY_STALE")
        else:
            _positive_int(current.membership_version, "current.membership_version")
            if not _valid_hash(current.membership_sha256):
                raise StrategyTargetApprovalError("APPROVAL_POLICY_STALE")
        _required_identifier(current.policy_ref, "current.policy_ref")
        _positive_int(current.policy_version, "current.policy_version")
        if not _valid_hash(current.policy_sha256):
            raise StrategyTargetApprovalError("APPROVAL_POLICY_STALE")
        _required_identifier(current.strategy_version_source_id, "current.strategy_version_source_id")
        _required_identifier(current.strategy_version_branch, "current.strategy_version_branch")
        if not _valid_hash(current.strategy_version_sha256):
            raise StrategyTargetApprovalError("APPROVAL_POLICY_STALE")
    except StrategyTargetApprovalError:
        raise StrategyTargetApprovalError("APPROVAL_POLICY_STALE") from None
    expected = (
        target["target_ref"],
        target["target_version"],
        target["strategy_version"],
        target["membership_version"],
        target["membership_sha256"],
        target["policy_ref"],
        target["policy_version"],
        target["policy_sha256"],
        strategy_version_source_id,
        strategy_version_branch,
        strategy_version_sha256,
    )
    observed = (
        current.target_ref,
        current.target_version,
        current.strategy_version,
        current.membership_version,
        current.membership_sha256,
        current.policy_ref,
        current.policy_version,
        current.policy_sha256,
        current.strategy_version_source_id,
        current.strategy_version_branch,
        current.strategy_version_sha256,
    )
    if observed != expected:
        raise StrategyTargetApprovalError("APPROVAL_POLICY_STALE")


async def _cas_update(
    db: AsyncSession,
    row: StrategyTargetApproval,
    values: dict[str, object],
    *,
    state: str = "APPROVED",
    rethrow_integrity: bool = False,
) -> bool:
    try:
        result = await db.execute(
            update(StrategyTargetApproval)
            .where(
                StrategyTargetApproval.approval_ref == row.approval_ref,
                StrategyTargetApproval.approval_version == row.approval_version,
                StrategyTargetApproval.record_version == row.record_version,
                StrategyTargetApproval.state == state,
            )
            .values(**values)
        )
        if result.rowcount != 1:
            return False
        for name, value in values.items():
            setattr(row, name, value)
        return True
    except IntegrityError:
        await db.rollback()
        if rethrow_integrity:
            raise
        raise StrategyTargetApprovalError("APPROVAL_STORE_UNAVAILABLE", ambiguous=True) from None
    except SQLAlchemyError:
        await db.rollback()
        raise StrategyTargetApprovalError("APPROVAL_STORE_UNAVAILABLE", ambiguous=True) from None


async def _find_operation_key(
    db: AsyncSession,
    *,
    owner_subject: str,
    principal_ref: str,
    actor_ref: str,
    delegate_ref: str,
    operation_key_hash: str,
) -> StrategyTargetApproval | None:
    try:
        result = await db.execute(
            select(StrategyTargetApproval).where(
                StrategyTargetApproval.owner_subject == owner_subject,
                StrategyTargetApproval.principal_ref == principal_ref,
                StrategyTargetApproval.actor_ref == actor_ref,
                StrategyTargetApproval.delegate_ref == delegate_ref,
                StrategyTargetApproval.operation_key_sha256 == operation_key_hash,
            )
        )
        return result.scalar_one_or_none()
    except SQLAlchemyError:
        raise StrategyTargetApprovalError("APPROVAL_STORE_UNAVAILABLE", ambiguous=True) from None


def _operation_request_sha256(row: StrategyTargetApproval, intent_id: str) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "approval_ref": row.approval_ref,
                "approval_version": row.approval_version,
                "target_sha256": row.target_sha256,
                "owner_subject": row.owner_subject,
                "principal_ref": row.principal_ref,
                "actor_ref": row.actor_ref,
                "delegate_ref": row.delegate_ref or None,
                "scope_ref": row.scope_ref,
                "account_ref": row.account_ref,
                "execution_domain_ref": row.execution_domain_ref,
                "strategy_ref": row.strategy_ref,
                "intent_id": intent_id,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _require_reserved_operation_binding(
    row: StrategyTargetApproval,
    operation_key: str,
    intent_id: str,
) -> None:
    """Require resolve/consume to repeat the exact durable operation binding."""

    if (
        row.operation_key_sha256 is None
        or row.operation_request_sha256 is None
        or row.intent_id is None
    ):
        raise StrategyTargetApprovalError("APPROVAL_OPERATION_CONFLICT")
    try:
        key_sha256 = operation_key_sha256(operation_key)
    except StrategyTargetApprovalError:
        raise
    if (
        row.operation_key_sha256 != key_sha256
        or row.intent_id != intent_id
        or row.operation_request_sha256 != _operation_request_sha256(row, intent_id)
    ):
        if row.state == "CONSUMED":
            raise StrategyTargetApprovalError("APPROVAL_CONSUMED_CONFLICT")
        raise StrategyTargetApprovalError("APPROVAL_OPERATION_CONFLICT")


def _event(
    row: StrategyTargetApproval,
    *,
    event_type: str,
    actor_subject: str,
    principal_ref: str,
    actor_ref: str,
    delegate_ref: str | None,
    occurred_at_ns: int,
    reason_code: str | None = None,
    operation_key_sha256: str | None = None,
    intent_id: str | None = None,
    intent_sha256: str | None = None,
    consumption_ref: str | None = None,
) -> StrategyTargetApprovalEvent:
    return StrategyTargetApprovalEvent(
        approval_ref=row.approval_ref,
        approval_version=row.approval_version,
        record_version=row.record_version,
        event_type=event_type,
        owner_subject=row.owner_subject,
        actor_subject=actor_subject,
        principal_ref=principal_ref,
        actor_ref=actor_ref,
        delegate_ref=_delegate_storage_value(delegate_ref),
        target_sha256=row.target_sha256,
        occurred_at_ns=occurred_at_ns,
        reason_code=reason_code,
        operation_key_sha256=operation_key_sha256,
        intent_id=intent_id,
        intent_sha256=intent_sha256,
        consumption_ref=consumption_ref,
    )


def _consumption_receipt(row: StrategyTargetApproval, disposition: str) -> dict[str, object]:
    if (
        row.state != "CONSUMED"
        or row.intent_id is None
        or row.consumption_ref is None
        or row.consumed_intent_sha256 is None
        or row.consumed_at_ns is None
        or row.consumed_record_version is None
    ):
        raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID")
    return {
        "disposition": disposition,
        "consumption_ref": row.consumption_ref,
        "approval_ref": row.approval_ref,
        "approval_version": row.approval_version,
        "consumed_record_version": row.consumed_record_version,
        "target_ref": row.target_ref,
        "target_version": row.target_version,
        "target_sha256": row.target_sha256,
        "intent_id": row.intent_id,
        "intent_sha256": row.consumed_intent_sha256,
        "consumed_at_ns": row.consumed_at_ns,
    }


def _scope_payload(scope: object) -> dict[str, object]:
    keys = (
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
    try:
        raw = {key: getattr(scope, key) for key in keys}
        raw["account_refs"] = list(raw["account_refs"])
    except (AttributeError, TypeError):
        raise StrategyTargetApprovalError("APPROVAL_SCOPE_MISMATCH") from None
    if (
        raw["account_ref"] is None
        or raw["strategy_ref"] is None
        or raw["account_refs"] != []
        or raw["manual_book_ref"] is not None
        or raw["group_id"] is not None
        or raw["leg_id"] is not None
    ):
        raise StrategyTargetApprovalError("APPROVAL_SCOPE_MISMATCH")
    return raw


def _identity_field(identity: object, field: str) -> Any:
    try:
        return getattr(identity, field)
    except (AttributeError, TypeError):
        raise StrategyTargetApprovalError("APPROVAL_IDENTITY_MISMATCH") from None


def _identity_role(identity: object) -> str:
    role = _identity_field(identity, "role")
    role_value = getattr(role, "value", role)
    if type(role_value) is not str:
        raise StrategyTargetApprovalError("APPROVAL_IDENTITY_MISMATCH")
    return role_value


def _validate_target(value: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID")
    try:
        if set(value) != _TARGET_KEYS:
            raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID")
    except (TypeError, ValueError):
        raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID") from None
    target = dict(value)
    if (
        type(target["schema_id"]) is not str
        or target["schema_id"] != "bt_api.approved_order_target"
        or type(target["schema_version"]) is not int
        or target["schema_version"] != 1
    ):
        raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID")
    _required_identifier(target["target_ref"], "target_ref")
    _positive_int(target["target_version"], "target_version")
    _required_text(target["owner_subject"], "owner_subject", 256)
    _required_identifier(target["principal_ref"], "principal_ref")
    _required_identifier(target["actor_ref"], "actor_ref")
    _delegate_storage_value(target["delegate_ref"])
    _required_identifier(target["scope_ref"], "scope_ref")
    _positive_int(target["strategy_version"], "strategy_version")
    membership_version = target["membership_version"]
    membership_digest = target["membership_sha256"]
    if membership_version is None:
        if membership_digest is not None:
            raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID")
    else:
        _positive_int(membership_version, "membership_version")
        if not _valid_hash(membership_digest):
            raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID")
    _required_text(target["instrument"], "instrument", 192, pattern=_INSTRUMENT)
    _required_identifier(target["metadata_version"], "metadata_version")
    if type(target["side"]) is not str or target["side"] not in {"BUY", "SELL"}:
        raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID")
    if type(target["position_effect"]) is not str or target["position_effect"] not in {
        "OPEN",
        "CLOSE",
        "CLOSE_TODAY",
        "CLOSE_YESTERDAY",
    }:
        raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID")
    if type(target["order_type"]) is not str or target["order_type"] not in {"MARKET", "LIMIT"}:
        raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID")
    if type(target["time_in_force"]) is not str or target["time_in_force"] not in {
        "GTC",
        "IOC",
        "FOK",
        "DAY",
    }:
        raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID")
    quantity, _ = _positive_decimal_text(target["quantity"], "quantity")
    price_raw = target["price"]
    if target["order_type"] == "MARKET":
        if price_raw is not None:
            raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID")
        price = None
    else:
        price, _ = _positive_decimal_text(price_raw, "price")
    if type(target["reduce_only"]) is not bool:
        raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID")
    if target["position_effect"] != "OPEN" and not target["reduce_only"]:
        raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID")
    if target["deadline_ns"] is not None:
        _positive_int(target["deadline_ns"], "deadline_ns")
    limits = target["limits"]
    if not isinstance(limits, Mapping):
        raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID")
    try:
        if set(limits) != _LIMIT_KEYS:
            raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID")
    except (TypeError, ValueError):
        raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID") from None
    normalized_limits: dict[str, str | None] = {}
    for field in ("max_quantity", "max_notional", "min_price", "max_price"):
        limit = limits[field]
        if field == "max_quantity" and limit is None:
            raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID")
        normalized_limits[field] = (
            None if limit is None else _positive_decimal_text(limit, f"limits.{field}")[1]
        )
    max_quantity = Decimal(normalized_limits["max_quantity"])
    if quantity > max_quantity:
        raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID")
    if target["order_type"] == "MARKET" and normalized_limits["max_notional"] is not None:
        raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID")
    if price is not None:
        if normalized_limits["min_price"] is not None and price < Decimal(normalized_limits["min_price"]):
            raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID")
        if normalized_limits["max_price"] is not None and price > Decimal(normalized_limits["max_price"]):
            raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID")
        if (
            normalized_limits["min_price"] is not None
            and normalized_limits["max_price"] is not None
            and Decimal(normalized_limits["min_price"]) > Decimal(normalized_limits["max_price"])
        ):
            raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID")
        if (
            normalized_limits["max_notional"] is not None
            and _exact_product(quantity, price) > Decimal(normalized_limits["max_notional"])
        ):
            raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID")
    target["limits"] = normalized_limits
    wire_scope = target["wire_scope"]
    if not isinstance(wire_scope, Mapping) or set(wire_scope) != _WIRE_SCOPE_KEYS:
        raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID")
    wire = dict(wire_scope)
    for field in ("execution_domain_ref", "account_ref", "strategy_ref"):
        _required_identifier(wire[field], f"wire_scope.{field}")
    if wire["account_refs"] != [] or type(wire["account_refs"]) is not list:
        raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID")
    for field in ("run_id", "portfolio_ref"):
        if wire[field] is not None:
            _required_identifier(wire[field], f"wire_scope.{field}")
    if any(wire[field] is not None for field in ("manual_book_ref", "group_id", "leg_id")):
        raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID")
    if membership_version is not None and wire["portfolio_ref"] is None:
        raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID")
    # Account and domain are represented by the authenticated wire scope; the
    # target vector intentionally carries them only inside that exact object.
    target["wire_scope"] = wire
    _required_identifier(target["policy_ref"], "policy_ref")
    _positive_int(target["policy_version"], "policy_version")
    if not _valid_hash(target["policy_sha256"]):
        raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID")
    return target


def _positive_decimal_text(value: object, field: str) -> tuple[Decimal, str]:
    if (
        type(value) is not str
        or len(value) > _DECIMAL_TEXT_MAX
        or not _DECIMAL.fullmatch(value)
    ):
        raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID")
    try:
        decimal = Decimal(value)
    except InvalidOperation:
        raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID") from None
    if not decimal.is_finite() or decimal <= 0 or _normalized_decimal(decimal) != value:
        raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID")
    return decimal, value


def _normalized_decimal(value: Decimal) -> str:
    with localcontext() as context:
        context.prec = max(28, len(value.as_tuple().digits) + 2)
        return format(value.normalize(), "f")


def _exact_product(left: Decimal, right: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = 2 * _DECIMAL_TEXT_MAX + 2
        return left * right


def _required_text(
    value: object,
    field: str,
    max_length: int,
    *,
    pattern: re.Pattern[str] | None = None,
) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > max_length
        or (pattern is not None and not pattern.fullmatch(value))
    ):
        raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID")
    return value


def _required_identifier(value: object, field: str) -> str:
    return _required_text(value, field, 128, pattern=_IDENTIFIER)


def _positive_int(value: object, field: str) -> int:
    if type(value) is not int or value <= 0:
        raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID")
    return value


def _delegate_storage_value(value: object) -> str:
    if value is None:
        return ""
    return _required_identifier(value, "delegate_ref")


def _valid_hash(value: object) -> bool:
    return type(value) is str and bool(_HEX_64.fullmatch(value))


def _now_ns(value: int | None) -> int:
    import time

    if value is None:
        return time.time_ns()
    if type(value) is not int or value <= 0:
        raise StrategyTargetApprovalError("APPROVAL_TARGET_INVALID")
    return value
