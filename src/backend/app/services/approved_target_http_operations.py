"""Identity-scoped idempotency for approved-target HTTP submissions."""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.approved_target_http_operation import ApprovedTargetHttpOperation
from app.models.strategy_target_approval import StrategyTargetApproval

_HEX_64 = re.compile(r"^[0-9a-f]{64}$")


class ApprovedTargetHttpOperationError(RuntimeError):
    """Finite operation mapping failure; store failures remain ambiguous."""

    def __init__(self, code: str, *, ambiguous: bool = False) -> None:
        self.code = code
        self.ambiguous = ambiguous
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ApprovedTargetHttpOperationClaim:
    intent_id: str
    created: bool


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="strict")).hexdigest()


async def reserve_approved_target_http_operation(
    db: AsyncSession,
    *,
    owner_subject: str,
    principal_ref: str,
    actor_ref: str,
    delegate_ref: str | None,
    idempotency_key: str,
    request_sha256: str,
    approval_ref: str,
    approval_version: int,
    target_sha256: str,
    selector_ref: str,
    scope_ref: str,
    account_ref: str,
    strategy_ref: str,
    now_ns: int | None = None,
) -> ApprovedTargetHttpOperationClaim:
    """Persist an identity-scoped key to one stable intent before SDK access.

    Exact retries are returned before mutable approval state is inspected, so
    a consumed, revoked or expired request can still reach Execution's
    idempotent journal lookup. A different key can never bind the same
    approval to a second intent.
    """

    if (
        type(request_sha256) is not str
        or not _HEX_64.fullmatch(request_sha256)
        or type(target_sha256) is not str
        or not _HEX_64.fullmatch(target_sha256)
        or type(approval_version) is not int
        or approval_version <= 0
    ):
        raise ApprovedTargetHttpOperationError("APPROVAL_TARGET_INVALID")

    delegate_value = delegate_ref or ""
    key_hash = _sha256_text(idempotency_key)
    filters = (
        ApprovedTargetHttpOperation.owner_subject == owner_subject,
        ApprovedTargetHttpOperation.principal_ref == principal_ref,
        ApprovedTargetHttpOperation.actor_ref == actor_ref,
        ApprovedTargetHttpOperation.delegate_ref == delegate_value,
        ApprovedTargetHttpOperation.operation_key_sha256 == key_hash,
    )
    approval_filter = ApprovedTargetHttpOperation.approval_ref == approval_ref
    try:
        existing = await _load_mapping(db, filters)
        if existing is not None:
            _require_same_request(
                existing,
                request_sha256=request_sha256,
                approval_ref=approval_ref,
                approval_version=approval_version,
                target_sha256=target_sha256,
                selector_ref=selector_ref,
                scope_ref=scope_ref,
                account_ref=account_ref,
                strategy_ref=strategy_ref,
            )
            return ApprovedTargetHttpOperationClaim(existing.intent_id, False)

        approval = await db.scalar(
            select(StrategyTargetApproval)
            .where(StrategyTargetApproval.approval_ref == approval_ref)
            .with_for_update()
        )
        if approval is None:
            raise ApprovedTargetHttpOperationError("APPROVAL_NOT_FOUND")
        _validate_approval_binding(
            approval,
            owner_subject=owner_subject,
            principal_ref=principal_ref,
            actor_ref=actor_ref,
            delegate_ref=delegate_value,
            approval_version=approval_version,
            target_sha256=target_sha256,
            scope_ref=scope_ref,
            account_ref=account_ref,
            strategy_ref=strategy_ref,
            now_ns=now_ns,
        )
        # A second idempotency key for this approval conflicts even when it
        # belongs to the same caller. The approval is a one-intent authority.
        approval_mapping = await _load_mapping(db, (approval_filter,))
        if approval_mapping is not None:
            raise ApprovedTargetHttpOperationError("APPROVAL_OPERATION_CONFLICT")

        operation = ApprovedTargetHttpOperation(
            owner_subject=owner_subject,
            principal_ref=principal_ref,
            actor_ref=actor_ref,
            delegate_ref=delegate_value,
            operation_key_sha256=key_hash,
            request_sha256=request_sha256,
            approval_ref=approval_ref,
            approval_version=approval_version,
            target_sha256=target_sha256,
            intent_id=uuid.uuid4().hex,
            selector_ref=selector_ref,
            scope_ref=scope_ref,
            account_ref=account_ref,
            strategy_ref=strategy_ref,
        )
        db.add(operation)
        await db.commit()
        return ApprovedTargetHttpOperationClaim(operation.intent_id, True)
    except ApprovedTargetHttpOperationError:
        if db.in_transaction():
            await db.rollback()
        raise
    except IntegrityError:
        await db.rollback()
        existing = await _load_mapping(db, filters)
        if existing is not None:
            try:
                _require_same_request(
                    existing,
                    request_sha256=request_sha256,
                    approval_ref=approval_ref,
                    approval_version=approval_version,
                    target_sha256=target_sha256,
                    selector_ref=selector_ref,
                    scope_ref=scope_ref,
                    account_ref=account_ref,
                    strategy_ref=strategy_ref,
                )
            except ApprovedTargetHttpOperationError:
                raise
            return ApprovedTargetHttpOperationClaim(existing.intent_id, False)
        approval_mapping = await _load_mapping(db, (approval_filter,))
        if approval_mapping is not None:
            raise ApprovedTargetHttpOperationError("APPROVAL_OPERATION_CONFLICT") from None
        raise ApprovedTargetHttpOperationError(
            "APPROVAL_STORE_UNAVAILABLE", ambiguous=True
        ) from None
    except SQLAlchemyError:
        if db.in_transaction():
            await db.rollback()
        raise ApprovedTargetHttpOperationError(
            "APPROVAL_STORE_UNAVAILABLE", ambiguous=True
        ) from None


async def _load_mapping(db: AsyncSession, filters: tuple[object, ...]):
    try:
        return await db.scalar(
            select(ApprovedTargetHttpOperation).where(*filters).limit(1)
        )
    except SQLAlchemyError:
        raise ApprovedTargetHttpOperationError(
            "APPROVAL_STORE_UNAVAILABLE", ambiguous=True
        ) from None


def _require_same_request(
    operation: ApprovedTargetHttpOperation,
    *,
    request_sha256: str,
    approval_ref: str,
    approval_version: int,
    target_sha256: str,
    selector_ref: str,
    scope_ref: str,
    account_ref: str,
    strategy_ref: str,
) -> None:
    if (
        operation.request_sha256 != request_sha256
        or operation.approval_ref != approval_ref
        or operation.approval_version != approval_version
        or operation.target_sha256 != target_sha256
        or operation.selector_ref != selector_ref
        or operation.scope_ref != scope_ref
        or operation.account_ref != account_ref
        or operation.strategy_ref != strategy_ref
    ):
        raise ApprovedTargetHttpOperationError("IDEMPOTENCY_CONFLICT")


def _validate_approval_binding(
    approval: StrategyTargetApproval,
    *,
    owner_subject: str,
    principal_ref: str,
    actor_ref: str,
    delegate_ref: str,
    approval_version: int,
    target_sha256: str,
    scope_ref: str,
    account_ref: str,
    strategy_ref: str,
    now_ns: int | None,
) -> None:
    if approval.owner_subject != owner_subject:
        raise ApprovedTargetHttpOperationError("APPROVAL_OWNER_BINDING_MISMATCH")
    if (
        approval.principal_ref != principal_ref
        or approval.actor_ref != actor_ref
        or approval.delegate_ref != delegate_ref
    ):
        raise ApprovedTargetHttpOperationError("APPROVAL_IDENTITY_MISMATCH")
    if (
        approval.scope_ref != scope_ref
        or approval.account_ref != account_ref
        or approval.strategy_ref != strategy_ref
    ):
        raise ApprovedTargetHttpOperationError("APPROVAL_SCOPE_MISMATCH")
    if approval.approval_version != approval_version:
        raise ApprovedTargetHttpOperationError("APPROVAL_VERSION_MISMATCH")
    if approval.target_sha256 != target_sha256:
        raise ApprovedTargetHttpOperationError("APPROVAL_TARGET_DIGEST_MISMATCH")
    if approval.state == "REVOKED":
        raise ApprovedTargetHttpOperationError("APPROVAL_REVOKED")
    if approval.state == "CONSUMED":
        raise ApprovedTargetHttpOperationError("APPROVAL_CONSUMED_CONFLICT")
    if approval.state != "APPROVED":
        raise ApprovedTargetHttpOperationError("APPROVAL_NOT_APPROVED")
    timestamp = now_ns
    if timestamp is None:
        import time

        timestamp = time.time_ns()
    if type(timestamp) is not int or timestamp <= 0:
        raise ApprovedTargetHttpOperationError("APPROVAL_TARGET_INVALID")
    if approval.expires_at_ns <= timestamp:
        raise ApprovedTargetHttpOperationError("APPROVAL_EXPIRED")
