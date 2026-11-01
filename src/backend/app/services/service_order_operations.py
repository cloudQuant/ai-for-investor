"""AFI-owned operation-key mapping for normal Execution manual submits."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.service_order_operation import ServiceOrderOperation


class ManualOrderOperationError(RuntimeError):
    """Finite persistence or idempotency failure for an HTTP manual submit."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class ManualOrderIdempotencyConflict(ManualOrderOperationError):
    """A caller reused an operation key for different authority or content."""

    def __init__(self) -> None:
        super().__init__("IDEMPOTENCY_CONFLICT")


@dataclass(frozen=True, slots=True)
class ManualOrderOperationClaim:
    operation: ServiceOrderOperation
    created: bool


def sha256_canonical_json(value: Mapping[str, object]) -> str:
    """Hash only deterministic, non-secret operation facts."""

    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def operation_key_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="strict")).hexdigest()


async def reserve_manual_order_operation(
    db: AsyncSession,
    *,
    owner_subject: str,
    principal_ref: str,
    actor_ref: str,
    delegate_ref: str | None,
    operation_key: str,
    request_sha256: str,
    scope_ref: str,
    account_ref: str,
    manual_book_ref: str,
) -> ManualOrderOperationClaim:
    """Commit the caller-to-intent mapping before any SDK/provider request.

    The unique key is scoped by JWT subject plus the server-mapped service
    principal, actor and delegate. Concurrent retries with identical content
    receive the same durable intent ID; a changed body or target is refused.
    """

    key_digest = operation_key_sha256(operation_key)
    delegate_value = delegate_ref or ""
    filters = (
        ServiceOrderOperation.owner_subject == owner_subject,
        ServiceOrderOperation.principal_ref == principal_ref,
        ServiceOrderOperation.actor_ref == actor_ref,
        ServiceOrderOperation.delegate_ref == delegate_value,
        ServiceOrderOperation.operation_key_sha256 == key_digest,
    )
    existing = await _find_operation(db, filters)
    if existing is not None:
        _require_same_request(
            existing,
            request_sha256=request_sha256,
            scope_ref=scope_ref,
            account_ref=account_ref,
            manual_book_ref=manual_book_ref,
        )
        return ManualOrderOperationClaim(existing, False)

    operation = ServiceOrderOperation(
        owner_subject=owner_subject,
        principal_ref=principal_ref,
        actor_ref=actor_ref,
        delegate_ref=delegate_value,
        operation_kind="manual_order",
        operation_key_sha256=key_digest,
        request_sha256=request_sha256,
        intent_id=uuid.uuid4().hex,
        scope_ref=scope_ref,
        account_ref=account_ref,
        manual_book_ref=manual_book_ref,
    )
    db.add(operation)
    try:
        await db.commit()
        return ManualOrderOperationClaim(operation, True)
    except IntegrityError:
        await db.rollback()
        existing = await _find_operation(db, filters)
        if existing is None:
            raise ManualOrderOperationError("OPERATION_STORE_UNAVAILABLE") from None
        _require_same_request(
            existing,
            request_sha256=request_sha256,
            scope_ref=scope_ref,
            account_ref=account_ref,
            manual_book_ref=manual_book_ref,
        )
        return ManualOrderOperationClaim(existing, False)
    except SQLAlchemyError:
        await db.rollback()
        raise ManualOrderOperationError("OPERATION_STORE_UNAVAILABLE") from None


async def record_manual_order_outcome(
    db: AsyncSession,
    operation: ServiceOrderOperation,
    *,
    service_code: str,
    record_state: str | None,
) -> None:
    """Persist a finite outcome marker; the SDK journal owns actual order facts."""

    persisted = await db.get(ServiceOrderOperation, operation.id)
    if persisted is None:
        raise ManualOrderOperationError("OPERATION_STORE_UNAVAILABLE")
    persisted.last_service_code = service_code
    persisted.last_record_state = record_state
    persisted.updated_at = datetime.now(timezone.utc)
    try:
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        raise ManualOrderOperationError("OPERATION_STORE_UNAVAILABLE") from None


async def _find_operation(db: AsyncSession, filters: tuple[object, ...]):
    try:
        result = await db.execute(select(ServiceOrderOperation).where(*filters))
        return result.scalar_one_or_none()
    except SQLAlchemyError:
        raise ManualOrderOperationError("OPERATION_STORE_UNAVAILABLE") from None


def _require_same_request(
    operation: ServiceOrderOperation,
    *,
    request_sha256: str,
    scope_ref: str,
    account_ref: str,
    manual_book_ref: str,
) -> None:
    if (
        operation.operation_kind != "manual_order"
        or operation.request_sha256 != request_sha256
        or operation.scope_ref != scope_ref
        or operation.account_ref != account_ref
        or operation.manual_book_ref != manual_book_ref
    ):
        raise ManualOrderIdempotencyConflict()


def decimal_text(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")
