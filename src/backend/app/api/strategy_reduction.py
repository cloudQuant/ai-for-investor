"""Owner-authorized reduction of one previously approved strategy target."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.afi_owner_scope import PersistedOwnerScope, require_persisted_human_principal
from app.api.deps import require_permission
from app.api.service_read import _resolve_access
from app.config import get_settings
from app.db.database import get_db
from app.models.permission import Permission
from app.models.strategy_target_approval import StrategyTargetApproval
from app.schemas.auth import TokenPayload
from app.services.approved_target_http_operations import (
    ApprovedTargetHttpOperationError,
    reserve_approved_target_http_operation,
)
from app.services.service_order_operations import sha256_canonical_json
from app.services.service_read.contracts import ServiceReadContractError
from app.services.strategy_reduction_control import (
    StrategyReductionControlError,
    StrategyReductionDeployment,
)
from app.services.strategy_target_approvals import (
    StrategyTargetApprovalError,
    canonical_target_json,
    canonical_target_sha256,
)

router = APIRouter(dependencies=[Depends(require_persisted_human_principal)])
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_DECIMAL_RE = re.compile(r"^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")
_SAFE_REASON_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_EXECUTION_STATES = frozenset(
    {
        "PENDING_ADMISSION",
        "PENDING_DISPATCH",
        "DISPATCHING",
        "ACKED",
        "PARTIALLY_FILLED",
        "FILLED",
        "CANCELLED",
        "REJECTED",
        "BLOCKED",
        "UNKNOWN",
    }
)
_TERMINAL_STATES = frozenset({"FILLED", "CANCELLED", "REJECTED", "BLOCKED"})


class StrategyReductionRequest(BaseModel):
    """Select an approved target; the caller cannot supply execution terms."""

    model_config = ConfigDict(extra="forbid", strict=True)

    scope_ref: str = Field(min_length=1, max_length=128)
    approval_ref: str = Field(min_length=1, max_length=128)
    approval_version: int = Field(ge=1)
    target_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("scope_ref", "approval_ref")
    @classmethod
    def validate_refs(cls, value: str) -> str:
        if not _IDENTIFIER_RE.fullmatch(value):
            raise ValueError("invalid identifier")
        return value


def get_strategy_reduction_deployment() -> StrategyReductionDeployment:
    """Parse the dedicated operator deployment only when this POST is called."""

    try:
        deployment = StrategyReductionDeployment.from_secret(
            get_settings().SERVICE_STRATEGY_REDUCTION_DEPLOYMENT_JSON
        )
    except StrategyReductionControlError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": exc.code},
        ) from None
    if deployment is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "DEPLOYMENT_NOT_CONFIGURED"},
        )
    return deployment


@router.post(
    "/service-orders/approved-targets/reduce",
    summary="Reduce one exact strategy run using an approved close target",
)
async def reduce_approved_strategy_target(
    payload: StrategyReductionRequest,
    response: Response,
    idempotency_key: str = Header(
        ...,
        alias="Idempotency-Key",
        min_length=1,
        max_length=128,
    ),
    owner: PersistedOwnerScope = Depends(require_persisted_human_principal),
    current_user: TokenPayload = Depends(
        require_permission(Permission.SUBMIT_APPROVED_STRATEGY_TARGET)
    ),
    db: AsyncSession = Depends(get_db),
    deployment: StrategyReductionDeployment = Depends(get_strategy_reduction_deployment),
) -> dict[str, Any]:
    """Submit one immutable approved CLOSE target through owner.reduce.

    Scope, account, strategy, run and target terms come from persisted AFI
    approval plus operator/service-read deployment bindings.  A returned fill
    is the target order's filled quantity; this endpoint does not claim that a
    strategy or account is flat.
    """

    if current_user.sub != owner.owner_subject or not _KEY_RE.fullmatch(idempotency_key):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"code": "OWNER_DENIED"})
    try:
        access = _resolve_access(current_user, payload.scope_ref, "approved_target")
    except (ServiceReadContractError, HTTPException):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "SCOPE_NOT_FOUND"}) from None
    binding = access.approved_target_bindings.get(payload.scope_ref)
    identity = access.application_identity
    if binding is None or identity is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "APPROVED_TARGET_NOT_CONFIGURED"},
        )
    try:
        profile = deployment.profile_for(
            subject=owner.owner_subject,
            selector_ref=payload.scope_ref,
            approved_target_scope_ref=binding.expected_scope_ref,
            application_identity=identity,
            approved_target_wire_scope=binding.wire_scope,
        )
    except StrategyReductionControlError as exc:
        _raise_deployment_error(exc)

    try:
        approval = await db.scalar(
            select(StrategyTargetApproval)
            .where(
                StrategyTargetApproval.approval_ref == payload.approval_ref,
                StrategyTargetApproval.owner_subject == owner.owner_subject,
            )
            .limit(1)
        )
    except SQLAlchemyError:
        if db.in_transaction():
            await db.rollback()
        raise _unavailable("APPROVAL_STORE_UNAVAILABLE") from None
    if approval is None:
        raise _approval_not_found()
    target = _validate_persisted_close_target(
        approval,
        owner_subject=owner.owner_subject,
        application_identity=identity,
        scope_ref=binding.expected_scope_ref,
        wire_scope=profile.wire_scope,
        approval_version=payload.approval_version,
        target_sha256=payload.target_sha256,
    )

    facts = {
        "operation_kind": "owner_strategy_reduction",
        "owner_subject": owner.owner_subject,
        "principal_ref": identity.principal_ref,
        "actor_ref": identity.actor_ref,
        "delegate_ref": identity.delegate_ref,
        "selector_ref": payload.scope_ref,
        "scope_ref": binding.expected_scope_ref,
        "account_ref": binding.account_ref,
        "strategy_ref": binding.strategy_ref,
        "wire_scope": _wire_scope_payload(profile.wire_scope),
        "approval_ref": payload.approval_ref,
        "approval_version": payload.approval_version,
        "target_sha256": payload.target_sha256,
    }
    try:
        claim = await reserve_approved_target_http_operation(
            db,
            owner_subject=owner.owner_subject,
            principal_ref=identity.principal_ref,
            actor_ref=identity.actor_ref,
            delegate_ref=identity.delegate_ref,
            idempotency_key=idempotency_key,
            request_sha256=sha256_canonical_json(facts),
            approval_ref=payload.approval_ref,
            approval_version=payload.approval_version,
            target_sha256=payload.target_sha256,
            selector_ref=payload.scope_ref,
            scope_ref=binding.expected_scope_ref,
            account_ref=binding.account_ref,
            strategy_ref=binding.strategy_ref,
        )
    except ApprovedTargetHttpOperationError as exc:
        _raise_mapping_error(exc)
    except SQLAlchemyError:
        if db.in_transaction():
            await db.rollback()
        raise _unavailable("APPROVAL_STORE_UNAVAILABLE") from None

    try:
        raw_reply = deployment.submit(
            profile,
            approval_ref=payload.approval_ref,
            approval_version=payload.approval_version,
            target_sha256=payload.target_sha256,
            intent_id=claim.intent_id,
        )
    except StrategyReductionControlError as exc:
        if exc.code == "OWNER_OPERATION_DENIED":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "OWNER_OPERATION_DENIED"},
            ) from None
        if exc.code == "DEPLOYMENT_INACTIVE_OR_EXPIRED":
            response.status_code = status.HTTP_409_CONFLICT
            return _not_dispatched_projection(
                claim.intent_id, "DEPLOYMENT_INACTIVE_OR_EXPIRED"
            )
        if exc.code == "OWNER_SERVICE_UNAVAILABLE":
            raise _unavailable("OWNER_SERVICE_UNAVAILABLE") from None
        projection = _unknown_projection(claim.intent_id, "OWNER_OUTCOME_UNKNOWN")
        response.status_code = status.HTTP_202_ACCEPTED
        return projection

    projection = _validate_owner_reply(
        raw_reply, claim.intent_id, approved_quantity=target["quantity"]
    )
    if projection["outcome"] in {"pending", "partial", "unknown_review_required"}:
        response.status_code = status.HTTP_202_ACCEPTED
    elif projection["outcome"] == "not_dispatched":
        response.status_code = status.HTTP_409_CONFLICT
    return projection


def _validate_persisted_close_target(
    approval: StrategyTargetApproval,
    *,
    owner_subject: str,
    application_identity: Any,
    scope_ref: str,
    wire_scope: Any,
    approval_version: int,
    target_sha256: str,
) -> Mapping[str, Any]:
    if (
        approval.approval_version != approval_version
        or approval.target_sha256 != target_sha256
        or approval.scope_ref != scope_ref
        or approval.owner_subject != owner_subject
        or approval.account_ref != wire_scope.account_ref
        or approval.strategy_ref != wire_scope.strategy_ref
        or approval.execution_domain_ref != wire_scope.execution_domain_ref
        or approval.principal_ref != application_identity.principal_ref
        or approval.actor_ref != application_identity.actor_ref
        or approval.delegate_ref != (application_identity.delegate_ref or "")
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "APPROVAL_SCOPE_MISMATCH"},
        )
    try:
        target = json.loads(approval.canonical_target_json)
        if (
            type(target) is not dict
            or canonical_target_json(target) != approval.canonical_target_json
            or canonical_target_sha256(target) != approval.target_sha256
        ):
            raise ValueError("stale target")
    except (TypeError, ValueError, json.JSONDecodeError, StrategyTargetApprovalError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "APPROVAL_TARGET_INVALID"},
        ) from None
    if (
        target.get("schema_id") != "bt_api.approved_order_target"
        or target.get("schema_version") != 1
        or target.get("owner_subject") != owner_subject
        or target.get("principal_ref") != application_identity.principal_ref
        or target.get("actor_ref") != application_identity.actor_ref
        or target.get("delegate_ref") != (application_identity.delegate_ref or "")
        or target.get("scope_ref") != scope_ref
        or target.get("wire_scope") != _wire_scope_payload(wire_scope)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "APPROVAL_SCOPE_MISMATCH"},
        )
    if target.get("position_effect") != "CLOSE" or target.get("reduce_only") is not True:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "TARGET_NOT_REDUCTION"},
        )
    return target


def _validate_owner_reply(
    value: object, intent_id: str, *, approved_quantity: object
) -> dict[str, Any]:
    fields = {
        "schema_id",
        "schema_version",
        "intent_id",
        "status",
        "stage",
        "execution_state",
        "filled_quantity",
        "is_terminal",
        "review_required",
        "reason_code",
    }
    if (
        not isinstance(value, Mapping)
        or set(value) != {"ok", "code", "result"}
        or value.get("ok") is not True
        or value.get("code") != "OK"
    ):
        return _unknown_projection(intent_id, "OWNER_REPLY_INVALID")
    result = value.get("result")
    outcome = result.get("reduction") if isinstance(result, Mapping) and set(result) == {"reduction"} else None
    if (
        not isinstance(outcome, Mapping)
        or set(outcome) != fields
        or outcome.get("schema_id") != "bt_api.owner_strategy_reduction_outcome"
        or type(outcome.get("schema_version")) is not int
        or outcome.get("schema_version") != 1
        or outcome.get("intent_id") != intent_id
        or outcome.get("status") not in {"NOT_DISPATCHED", "PENDING", "PARTIAL", "FILLED", "TERMINAL", "UNKNOWN"}
        or outcome.get("stage") not in {"AUTHORITY", "EXECUTION"}
        or type(outcome.get("is_terminal")) is not bool
        or type(outcome.get("review_required")) is not bool
        or type(outcome.get("reason_code")) is not str
        or not _SAFE_REASON_RE.fullmatch(outcome["reason_code"])
        or type(outcome.get("filled_quantity")) is not str
        or not _DECIMAL_RE.fullmatch(outcome["filled_quantity"])
        or type(approved_quantity) is not str
        or not _DECIMAL_RE.fullmatch(approved_quantity)
    ):
        return _unknown_projection(intent_id, "OWNER_REPLY_INVALID")
    state = outcome.get("execution_state")
    if state is not None and (type(state) is not str or state not in _EXECUTION_STATES):
        return _unknown_projection(intent_id, "OWNER_REPLY_INVALID")
    status_text = str(outcome["status"])
    expected_terminal = state in _TERMINAL_STATES if state is not None else False
    expected_status = (
        "FILLED"
        if state == "FILLED"
        else "PARTIAL"
        if state == "PARTIALLY_FILLED"
        else "UNKNOWN"
        if state == "UNKNOWN"
        else "TERMINAL"
        if state in _TERMINAL_STATES
        else "PENDING"
    ) if state is not None else status_text
    if (
        outcome["is_terminal"] is not expected_terminal
        or status_text != expected_status
        or (state is not None and outcome["stage"] != "EXECUTION")
        or (
            state is None
            and status_text not in {"NOT_DISPATCHED", "UNKNOWN"}
        )
        or (status_text == "UNKNOWN" and outcome["review_required"] is not True)
        or (state is None and outcome["filled_quantity"] != "0")
        or (status_text == "NOT_DISPATCHED" and state is not None)
        or (
            status_text == "NOT_DISPATCHED"
            and (outcome["review_required"] or outcome["filled_quantity"] != "0")
        )
    ):
        return _unknown_projection(intent_id, "OWNER_REPLY_INVALID")
    try:
        filled = Decimal(outcome["filled_quantity"])
        maximum = Decimal(approved_quantity)
    except (InvalidOperation, ValueError):
        return _unknown_projection(intent_id, "OWNER_REPLY_INVALID")
    if (
        not filled.is_finite()
        or not maximum.is_finite()
        or maximum <= 0
        or filled < 0
        or filled > maximum
        or (status_text == "FILLED" and filled != maximum)
        or (status_text == "PARTIAL" and not Decimal(0) < filled < maximum)
    ):
        return _unknown_projection(intent_id, "OWNER_REPLY_INVALID")
    return {
        "operation_kind": "owner_strategy_reduction",
        "intent_id": intent_id,
        "outcome": {
            "NOT_DISPATCHED": "not_dispatched",
            "PENDING": "pending",
            "PARTIAL": "partial",
            "FILLED": "filled",
            "TERMINAL": "terminal",
            "UNKNOWN": "unknown_review_required",
        }[status_text],
        "execution": dict(outcome),
        "flatness": "not_established",
        "authority": "Execution order result for the approved target; not a position or account flatness claim",
    }


def _unknown_projection(intent_id: str, code: str) -> dict[str, Any]:
    return {
        "operation_kind": "owner_strategy_reduction",
        "intent_id": intent_id,
        "outcome": "unknown_review_required",
        "execution": {
            "schema_id": "bt_api.owner_strategy_reduction_outcome",
            "schema_version": 1,
            "intent_id": intent_id,
            "status": "UNKNOWN",
            "stage": "EXECUTION",
            "execution_state": None,
            "filled_quantity": "0",
            "is_terminal": False,
            "review_required": True,
            "reason_code": code if _SAFE_REASON_RE.fullmatch(code) else "OWNER_OUTCOME_UNKNOWN",
        },
        "flatness": "not_established",
        "authority": "Execution order result for the approved target; not a position or account flatness claim",
    }


def _not_dispatched_projection(intent_id: str, code: str) -> dict[str, Any]:
    return {
        "operation_kind": "owner_strategy_reduction",
        "intent_id": intent_id,
        "outcome": "not_dispatched",
        "execution": {
            "schema_id": "bt_api.owner_strategy_reduction_outcome",
            "schema_version": 1,
            "intent_id": intent_id,
            "status": "NOT_DISPATCHED",
            "stage": "AUTHORITY",
            "execution_state": None,
            "filled_quantity": "0",
            "is_terminal": False,
            "review_required": False,
            "reason_code": code,
        },
        "flatness": "not_established",
        "authority": "Deployment was inactive before the owner operation; no execution result is inferred",
    }


def _wire_scope_payload(scope: object) -> dict[str, object]:
    return {
        "execution_domain_ref": getattr(scope, "execution_domain_ref", None),
        "account_ref": getattr(scope, "account_ref", None),
        "account_refs": list(getattr(scope, "account_refs", ())),
        "strategy_ref": getattr(scope, "strategy_ref", None),
        "run_id": getattr(scope, "run_id", None),
        "manual_book_ref": getattr(scope, "manual_book_ref", None),
        "portfolio_ref": getattr(scope, "portfolio_ref", None),
        "group_id": getattr(scope, "group_id", None),
        "leg_id": getattr(scope, "leg_id", None),
    }


def _raise_deployment_error(error: StrategyReductionControlError) -> None:
    if error.code == "PROFILE_NOT_AUTHORIZED":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "SCOPE_NOT_FOUND"}) from None
    if error.code == "PROFILE_SCOPE_MISMATCH":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"code": "SCOPE_DENIED"}) from None
    if error.code == "PROFILE_AMBIGUOUS":
        raise _unavailable("DEPLOYMENT_AMBIGUOUS") from None
    raise _unavailable(error.code) from None


def _raise_mapping_error(error: ApprovedTargetHttpOperationError) -> None:
    if error.ambiguous or error.code == "APPROVAL_STORE_UNAVAILABLE":
        raise _unavailable("APPROVAL_STORE_UNAVAILABLE") from None
    if error.code in {"APPROVAL_NOT_FOUND", "APPROVAL_OWNER_BINDING_MISMATCH"}:
        raise _approval_not_found()
    if error.code in {"APPROVAL_IDENTITY_MISMATCH", "APPROVAL_SCOPE_MISMATCH"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"code": error.code}) from None
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": error.code}) from None


def _approval_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "APPROVAL_NOT_FOUND", "message": "The approved target was not found."},
    )


def _unavailable(code: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"code": code, "message": "The reduction outcome is unavailable; inspect the same operation key."},
    )
