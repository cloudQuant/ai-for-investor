"""Authenticated manual-order submission through the configured SDK owner."""

from __future__ import annotations

import re
from collections.abc import Mapping
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.afi_owner_scope import require_persisted_owner_scope
from app.api.deps import require_permission
from app.api.service_read import _order_payload, _resolve_access
from app.db.database import get_db
from app.models.permission import Permission
from app.schemas.auth import TokenPayload
from app.services.service_order_operations import (
    ManualOrderOperationError,
    decimal_text,
    record_manual_order_outcome,
    reserve_manual_order_operation,
    sha256_canonical_json,
)
from app.services.service_read.client import (
    ServiceReadUnavailableError,
    _order_view,
)
from app.services.service_read.contracts import ServiceReadContractError

router = APIRouter(
    prefix="/service-orders",
    tags=["Service Orders"],
    dependencies=[Depends(require_persisted_owner_scope)],
)

_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_INSTRUMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,191}$")
_SAFE_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_FORBIDDEN_CODES = frozenset(
    {
        "CAPABILITY_UNAVAILABLE",
        "DENIED",
        "NOT_REGISTERED",
        "POLICY_REQUIREMENT_UNMET",
        "ROLE_NOT_AUTHORIZED",
        "SCOPE_DENIED",
        "STALE_EPOCH",
    }
)
_CONFLICT_CODES = frozenset(
    {"ADMISSION_REQUIRED", "INTENT_CONFLICT", "OWNER_LEASE_UNAVAILABLE", "STATE_CONFLICT"}
)


class ManualOrderRequest(BaseModel):
    """Only order terms and a server-configured selector are client supplied."""

    model_config = ConfigDict(extra="forbid")

    scope_ref: str = Field(min_length=1, max_length=128)
    instrument: str = Field(min_length=1, max_length=192)
    side: Literal["BUY", "SELL"]
    position_effect: Literal["OPEN", "CLOSE", "CLOSE_TODAY", "CLOSE_YESTERDAY"]
    order_type: Literal["MARKET", "LIMIT"]
    quantity: Decimal = Field(gt=0, allow_inf_nan=False)
    price: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)
    time_in_force: Literal["GTC", "IOC", "FOK", "DAY"] = "GTC"
    reduce_only: bool = False

    @model_validator(mode="after")
    def validate_manual_order(self) -> ManualOrderRequest:
        if not _KEY_RE.fullmatch(self.scope_ref):
            raise ValueError("invalid configured scope selector")
        if not _INSTRUMENT_RE.fullmatch(self.instrument):
            raise ValueError("invalid instrument")
        if self.order_type == "LIMIT" and self.price is None:
            raise ValueError("limit orders require a price")
        if self.order_type == "MARKET" and self.price is not None:
            raise ValueError("market orders do not carry a price")
        if self.position_effect != "OPEN" and not self.reduce_only:
            raise ValueError("closing orders must be reduce_only")
        return self


@router.post("/manual", response_model=None)
async def submit_manual_order(
    request: ManualOrderRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: TokenPayload = Depends(require_permission(Permission.SUBMIT_MANUAL_ORDER)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Submit a manual intent through the configured Execution account owner.

    The route never accepts an identity, account, strategy, book, scope object,
    intent ID, or approval claim from the caller. An Idempotency-Key is stored
    before the SDK call and always maps to the same intent across retries.
    """

    key = _require_idempotency_key(idempotency_key)
    access = _resolve_access(current_user, request.scope_ref, "order_submit")
    binding = access.order_submit_bindings.get(request.scope_ref)
    identity = access.application_identity
    if binding is None or identity is None:
        raise _not_configured()
    metadata_version = binding.instrument_metadata_versions.get(request.instrument)
    if metadata_version is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "INSTRUMENT_METADATA_VERSION_NOT_CONFIGURED",
                "message": "The trusted order deployment has no metadata version for this instrument.",
            },
        )

    intent_facts: dict[str, object] = {
        "scope_ref": request.scope_ref,
        "account_ref": binding.account_ref,
        "manual_book_ref": binding.manual_book_ref,
        "instrument": request.instrument,
        "metadata_version": metadata_version,
        "side": request.side,
        "position_effect": request.position_effect,
        "order_type": request.order_type,
        "quantity": decimal_text(request.quantity),
        "price": decimal_text(request.price),
        "time_in_force": request.time_in_force,
        "reduce_only": request.reduce_only,
    }
    request_hash = sha256_canonical_json(intent_facts)
    try:
        claim = await reserve_manual_order_operation(
            db,
            owner_subject=current_user.sub,
            principal_ref=identity.principal_ref,
            actor_ref=identity.actor_ref,
            delegate_ref=identity.delegate_ref,
            operation_key=key,
            request_sha256=request_hash,
            scope_ref=binding.scope_ref,
            account_ref=binding.account_ref,
            manual_book_ref=binding.manual_book_ref,
        )
    except ManualOrderOperationError as error:
        if error.code == "IDEMPOTENCY_CONFLICT":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": error.code, "message": "The operation key is already bound."},
            ) from None
        raise _operation_store_unavailable() from None

    intent_id = claim.operation.intent_id
    arguments: dict[str, object] = {
        "intent_id": intent_id,
        "signal_id": f"afi-manual-{intent_id}",
        "instrument": request.instrument,
        "side": request.side,
        "position_effect": request.position_effect,
        "order_type": request.order_type,
        "quantity": decimal_text(request.quantity),
        "price": decimal_text(request.price),
        "time_in_force": request.time_in_force,
        "reduce_only": request.reduce_only,
        "metadata_version": metadata_version,
        "deadline_ns": None,
        "tags": {},
    }
    try:
        service_reply = await access.worker.submit_manual_order(request.scope_ref, arguments)
    except ServiceReadUnavailableError as error:
        await _record_failed_attempt(db, claim.operation, _safe_code(error.code))
        raise _map_service_error(error.code) from None
    except Exception as error:  # noqa: BLE001 - expose only a finite code to HTTP
        await _record_failed_attempt(db, claim.operation, _error_code(error))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": _error_code(error), "message": "The execution service did not answer."},
        ) from None

    service_code, record = _parse_submit_reply(service_reply, intent_id)
    record_state = record.get("state") if record is not None else None
    try:
        await record_manual_order_outcome(
            db,
            claim.operation,
            service_code=service_code,
            record_state=record_state if isinstance(record_state, str) else None,
        )
    except ManualOrderOperationError:
        # The operation key and intent ID are already committed. A retry uses
        # that exact ID and lets Execution return its durable journal result.
        raise _operation_store_unavailable() from None

    if service_code in _FORBIDDEN_CODES:
        raise _map_service_error(service_code)
    if service_code == "INVALID_REQUEST":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": service_code, "message": "The execution service rejected the intent."},
        )
    if service_code in _CONFLICT_CODES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": service_code, "message": "The execution service did not accept the intent."},
        )
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": service_code, "message": "The execution outcome is not available."},
        )

    result: dict[str, Any] = {
        "operation_kind": "manual_order",
        "intent_id": intent_id,
        "actor_ref": identity.actor_ref,
        "delegate_ref": identity.delegate_ref,
        "account_ref": binding.account_ref,
        "manual_book_ref": binding.manual_book_ref,
        "service_code": service_code,
        "record": dict(record),
    }
    state = record.get("state")
    if state == "UNKNOWN" or record.get("review_required") is True:
        result["outcome"] = "unknown_review_required"
        return result
    result["outcome"] = "durable_record"
    return result


def _parse_submit_reply(
    payload: object, expected_intent_id: str
) -> tuple[str, Mapping[str, Any] | None]:
    """Validate the Execution business reply returned by ``runtime.call``.

    The SDK runtime has already validated and unwrapped the wire envelope, so
    this payload is the order-entry adapter's ``{ok, code, result}`` reply.
    """

    if not isinstance(payload, Mapping) or set(payload) != {"ok", "code", "result"}:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "INVALID_EXECUTION_REPLY", "message": "The execution service reply was invalid."},
        )
    ok = payload.get("ok")
    code = _safe_code(payload.get("code"))
    if type(ok) is not bool or (ok and code != "OK") or (not ok and code == "OK"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "INVALID_EXECUTION_REPLY", "message": "The execution service reply was invalid."},
        )
    result = payload.get("result")
    if not isinstance(result, Mapping) or set(result) != {"found", "record"}:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "INVALID_EXECUTION_REPLY", "message": "The execution service reply was invalid."},
        )
    found = result.get("found")
    record = result.get("record")
    if found is False and record is None and not ok:
        return code, None
    if found is not True:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "INVALID_EXECUTION_REPLY", "message": "The execution service reply was invalid."},
        )
    if (
        not isinstance(record, Mapping)
        or record.get("intent_id") != expected_intent_id
        or type(record.get("state")) is not str
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "INVALID_EXECUTION_REPLY", "message": "The execution service reply was invalid."},
        )
    try:
        # Reuse the existing order DTO allowlist so this write response cannot
        # expose internal journal columns added by Execution later.
        view = _order_view({"found": True, "record": record}, expected_intent_id)
    except (ServiceReadContractError, ServiceReadUnavailableError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "INVALID_EXECUTION_REPLY", "message": "The execution service reply was invalid."},
        ) from None
    return code, _order_payload(view)


def _require_idempotency_key(value: str | None) -> str:
    if type(value) is not str or not _KEY_RE.fullmatch(value):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "IDEMPOTENCY_KEY_REQUIRED", "message": "A valid Idempotency-Key is required."},
        )
    return value


def _safe_code(value: object) -> str:
    return value if type(value) is str and _SAFE_CODE_RE.fullmatch(value) else "SERVICE_READ_FAILED"


def _error_code(error: BaseException) -> str:
    return _safe_code(getattr(error, "code", None))


async def _record_failed_attempt(db: AsyncSession, operation: Any, code: str) -> None:
    try:
        await record_manual_order_outcome(db, operation, service_code=code, record_state=None)
    except ManualOrderOperationError:
        raise _operation_store_unavailable() from None


def _not_configured() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"code": "ORDER_SUBMIT_NOT_CONFIGURED", "message": "No manual-order service is configured."},
    )


def _operation_store_unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"code": "OPERATION_STORE_UNAVAILABLE", "message": "The operation identity was not persisted."},
    )


def _map_service_error(code: str) -> HTTPException:
    if code in _FORBIDDEN_CODES:
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": code, "message": "The execution service denied this order scope."},
        )
    if code in _CONFLICT_CODES:
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": code, "message": "The execution service did not accept the intent."},
        )
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"code": code, "message": "The execution service did not answer."},
    )
