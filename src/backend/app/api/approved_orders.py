"""HTTP workflow for approved single-strategy Execution targets."""

from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from collections.abc import Mapping
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.api.service_read import _resolve_access
from app.db.database import get_db
from app.models.permission import Permission
from app.models.portfolio_composition import PortfolioCompositionVersion
from app.models.strategy_approval_authority import (
    StrategyOrderApprovalPolicyHead,
    StrategyOrderApprovalPolicyVersion,
)
from app.models.strategy_target_approval import StrategyTargetApproval
from app.schemas.auth import TokenPayload
from app.services.approved_target_http_operations import (
    ApprovedTargetHttpOperationError,
    reserve_approved_target_http_operation,
)
from app.services.service_order_operations import sha256_canonical_json
from app.services.service_read.client import ServiceReadUnavailableError
from app.services.service_read.contracts import ServiceReadContractError
from app.services.strategy_approval_authority import (
    approve_strategy_order_target,
    canonical_policy_sha256,
    portfolio_membership_sha256,
    validate_target_against_policy,
)
from app.services.strategy_target_approvals import (
    StrategyTargetApprovalError,
    canonical_target_sha256,
    revoke_approved_order_target,
)

router = APIRouter(prefix="/service-orders/approved-targets", tags=["Approved Orders"])

_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_DECIMAL_RE = re.compile(r"^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_INSTRUMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,191}$")


class ApprovalPolicyPublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    policy: dict[str, object]


class ApprovedTargetCreateRequest(BaseModel):
    """Trade terms and version selectors only; authority is server derived."""

    model_config = ConfigDict(extra="forbid", strict=True)

    scope_ref: str = Field(min_length=1, max_length=128)
    strategy_version: int = Field(ge=1)
    instrument: str = Field(min_length=1, max_length=192)
    metadata_version: str = Field(min_length=1, max_length=128)
    side: Literal["BUY", "SELL"]
    position_effect: Literal["OPEN", "CLOSE", "CLOSE_TODAY", "CLOSE_YESTERDAY"]
    order_type: Literal["MARKET", "LIMIT"]
    quantity: str = Field(min_length=1, max_length=128)
    price: str | None = Field(default=None, min_length=1, max_length=128)
    time_in_force: Literal["GTC", "IOC", "FOK", "DAY"] = "GTC"
    reduce_only: bool = False
    deadline_ns: int | None = None
    expires_in_seconds: int = Field(default=300, ge=1, le=86_400)

    @field_validator("scope_ref", "metadata_version")
    @classmethod
    def validate_identifiers(cls, value: str) -> str:
        if not _IDENTIFIER_RE.fullmatch(value):
            raise ValueError("invalid identifier")
        return value

    @field_validator("instrument")
    @classmethod
    def validate_instrument(cls, value: str) -> str:
        if not _INSTRUMENT_RE.fullmatch(value):
            raise ValueError("invalid instrument")
        return value

    @field_validator("quantity", "price")
    @classmethod
    def validate_decimal_text(cls, value: str | None) -> str | None:
        if value is not None and not _DECIMAL_RE.fullmatch(value):
            raise ValueError("decimal values must be canonical strings")
        return value

    @model_validator(mode="after")
    def validate_order(self) -> ApprovedTargetCreateRequest:
        if self.order_type == "LIMIT" and self.price is None:
            raise ValueError("limit orders require a price")
        if self.order_type == "MARKET" and self.price is not None:
            raise ValueError("market orders do not carry a price")
        if self.position_effect != "OPEN" and not self.reduce_only:
            raise ValueError("closing orders must be reduce_only")
        if self.deadline_ns is not None and self.deadline_ns <= 0:
            raise ValueError("deadline_ns must be positive")
        return self


class ApprovedTargetSubmitRequest(BaseModel):
    """Only the approval claim and a trusted deployment selector are accepted."""

    model_config = ConfigDict(extra="forbid", strict=True)

    scope_ref: str = Field(min_length=1, max_length=128)
    approval_ref: str = Field(min_length=1, max_length=128)
    approval_version: int = Field(ge=1)
    target_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("scope_ref", "approval_ref")
    @classmethod
    def validate_identifiers(cls, value: str) -> str:
        if not _IDENTIFIER_RE.fullmatch(value):
            raise ValueError("invalid identifier")
        return value


class ApprovedTargetRevokeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    scope_ref: str = Field(min_length=1, max_length=128)
    approval_version: int = Field(ge=1)
    reason_code: str = Field(min_length=1, max_length=128)

    @field_validator("scope_ref")
    @classmethod
    def validate_scope(cls, value: str) -> str:
        if not _IDENTIFIER_RE.fullmatch(value):
            raise ValueError("invalid identifier")
        return value

    @field_validator("reason_code")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        if not re.fullmatch(r"^[a-z][a-z0-9_]{0,127}$", value):
            raise ValueError("invalid reason code")
        return value


@router.post("/policies/{policy_ref}", status_code=status.HTTP_201_CREATED)
async def publish_approval_policy(
    policy_ref: str,
    payload: ApprovalPolicyPublishRequest,
    current_user: TokenPayload = Depends(
        require_permission(Permission.MANAGE_STRATEGY_ORDER_APPROVAL_POLICY)
    ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Publish a versioned AFI target-eligibility policy (not live Risk policy)."""

    if not _IDENTIFIER_RE.fullmatch(policy_ref):
        raise HTTPException(status_code=422, detail={"code": "INVALID_POLICY_REF"})
    from app.services.strategy_approval_authority import publish_strategy_order_approval_policy

    now_ns = time.time_ns()
    try:
        row = await publish_strategy_order_approval_policy(
            db,
            owner_subject=current_user.sub,
            policy_ref=policy_ref,
            policy=payload.policy,
            published_by_subject=current_user.sub,
            # The authenticated AFI user subject is the policy publisher's
            # principal and actor; it is not the later Execution WireIdentity.
            published_by_principal_ref=current_user.sub,
            published_by_actor_ref=current_user.sub,
            published_by_delegate_ref=None,
            published_at_ns=now_ns,
        )
        await db.commit()
    except StrategyTargetApprovalError as error:
        if db.in_transaction():
            await db.rollback()
        raise _approval_error(error) from None
    except SQLAlchemyError:
        if db.in_transaction():
            await db.rollback()
        raise _unavailable("APPROVAL_STORE_UNAVAILABLE") from None
    return {
        "policy_ref": row.policy_ref,
        "policy_version": row.policy_version,
        "policy_sha256": row.policy_sha256,
        "status": "published",
        "authority": "AFI target eligibility policy; Execution Risk admission remains independent",
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_approved_target(
    payload: ApprovedTargetCreateRequest,
    current_user: TokenPayload = Depends(
        require_permission(Permission.APPROVE_STRATEGY_ORDER_TARGET)
    ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Create and approve one immutable target under a dedicated permission."""

    access = _resolve_access(current_user, payload.scope_ref, "approved_target")
    binding = access.approved_target_bindings.get(payload.scope_ref)
    identity = access.application_identity
    if binding is None or identity is None:
        raise _not_configured()
    now_ns = time.time_ns()
    policy_head = await db.get(StrategyOrderApprovalPolicyHead, current_user.sub)
    if policy_head is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "APPROVAL_POLICY_STALE", "message": "No AFI approval policy is published."},
        )
    policy_row = await db.scalar(
        select(StrategyOrderApprovalPolicyVersion).where(
            StrategyOrderApprovalPolicyVersion.owner_subject == current_user.sub,
            StrategyOrderApprovalPolicyVersion.policy_ref == policy_head.policy_ref,
            StrategyOrderApprovalPolicyVersion.policy_version == policy_head.policy_version,
        )
    )
    if (
        policy_row is None
        or policy_row.policy_sha256 != policy_head.policy_sha256
        or canonical_policy_sha256(json.loads(policy_row.canonical_policy_json))
        != policy_head.policy_sha256
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "APPROVAL_POLICY_STALE", "message": "The AFI approval policy is unavailable."},
        )

    membership_version: int | None = None
    membership_hash: str | None = None
    portfolio_ref = getattr(binding.wire_scope, "portfolio_ref", None)
    if portfolio_ref is not None:
        membership_version = await db.scalar(
            select(func.max(PortfolioCompositionVersion.membership_version)).where(
                PortfolioCompositionVersion.owner_subject == current_user.sub,
                PortfolioCompositionVersion.portfolio_ref == portfolio_ref,
            )
        )
        if membership_version is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "APPROVAL_POLICY_STALE", "message": "The configured membership is unavailable."},
            )
        membership = await db.scalar(
            select(PortfolioCompositionVersion).where(
                PortfolioCompositionVersion.owner_subject == current_user.sub,
                PortfolioCompositionVersion.portfolio_ref == portfolio_ref,
                PortfolioCompositionVersion.membership_version == membership_version,
            )
        )
        if membership is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "APPROVAL_POLICY_STALE", "message": "The configured membership is unavailable."},
            )
        members = membership.members
        if not isinstance(members, list) or not any(
            isinstance(member, dict)
            and member.get("kind") == "strategy"
            and member.get("ref") == binding.strategy_ref
            for member in members
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "APPROVAL_SCOPE_MISMATCH", "message": "The strategy is outside the configured membership."},
            )
        membership_hash = portfolio_membership_sha256(membership)

    scope = _wire_scope_payload(binding.wire_scope)
    target: dict[str, object] = {
        "schema_id": "bt_api.approved_order_target",
        "schema_version": 1,
        "target_ref": uuid.uuid4().hex,
        "target_version": 1,
        "owner_subject": current_user.sub,
        "principal_ref": identity.principal_ref,
        "actor_ref": identity.actor_ref,
        "delegate_ref": identity.delegate_ref,
        "scope_ref": binding.expected_scope_ref,
        "wire_scope": scope,
        "strategy_version": payload.strategy_version,
        "membership_version": membership_version,
        "membership_sha256": membership_hash,
        "instrument": payload.instrument,
        "metadata_version": payload.metadata_version,
        "side": payload.side,
        "position_effect": payload.position_effect,
        "order_type": payload.order_type,
        "quantity": payload.quantity,
        "price": payload.price,
        "time_in_force": payload.time_in_force,
        "reduce_only": payload.reduce_only,
        "deadline_ns": payload.deadline_ns,
        "limits": dict(json.loads(policy_row.canonical_policy_json)["limits"]),
        "policy_ref": policy_row.policy_ref,
        "policy_version": policy_row.policy_version,
        "policy_sha256": policy_row.policy_sha256,
    }
    try:
        validate_target_against_policy(target, json.loads(policy_row.canonical_policy_json))
        approval = await approve_strategy_order_target(
            db,
            target=target,
            owner_subject=current_user.sub,
            expected_scope_ref=binding.expected_scope_ref,
            target_identity=identity,
            target_wire_scope=binding.wire_scope,
            approved_by_subject=current_user.sub,
            approved_by_principal_ref=current_user.sub,
            approved_by_actor_ref=current_user.sub,
            approved_by_delegate_ref=None,
            approved_at_ns=now_ns,
            expires_at_ns=now_ns + payload.expires_in_seconds * 1_000_000_000,
        )
    except StrategyTargetApprovalError as error:
        raise _approval_error(error) from None
    except ServiceReadContractError:
        raise _not_configured() from None
    except SQLAlchemyError:
        if db.in_transaction():
            await db.rollback()
        raise _unavailable("APPROVAL_STORE_UNAVAILABLE") from None
    return {
        "approval_ref": approval.approval_ref,
        "approval_version": approval.approval_version,
        "target_ref": approval.target_ref,
        "target_version": approval.target_version,
        "target_sha256": approval.target_sha256,
        "state": approval.state,
        "expires_at_ns": approval.expires_at_ns,
        "decision_actor_subject": current_user.sub,
        "authority": "AFI-approved immutable target; not an Execution admission or provider result",
    }


@router.post("/{approval_ref}/revoke")
async def revoke_approved_target(
    approval_ref: str,
    payload: ApprovedTargetRevokeRequest,
    current_user: TokenPayload = Depends(
        require_permission(Permission.APPROVE_STRATEGY_ORDER_TARGET)
    ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Revoke an owner-scoped, unconsumed target using AFI's CAS service."""

    access = _resolve_access(current_user, payload.scope_ref, "approved_target")
    binding = access.approved_target_bindings.get(payload.scope_ref)
    if binding is None or access.application_identity is None:
        raise _not_configured()
    approval = await db.scalar(
        select(StrategyTargetApproval).where(
            StrategyTargetApproval.approval_ref == approval_ref,
            StrategyTargetApproval.owner_subject == current_user.sub,
        )
    )
    if approval is None:
        raise _approval_not_found()
    if (
        approval.scope_ref != binding.expected_scope_ref
        or approval.account_ref != binding.account_ref
        or approval.strategy_ref != binding.strategy_ref
        or approval.principal_ref != access.application_identity.principal_ref
        or approval.actor_ref != access.application_identity.actor_ref
        or approval.delegate_ref != (access.application_identity.delegate_ref or "")
    ):
        raise _approval_not_found()
    try:
        record_version = await revoke_approved_order_target(
            db,
            approval_ref=approval_ref,
            approval_version=payload.approval_version,
            owner_subject=current_user.sub,
            revoker_subject=current_user.sub,
            revoker_principal_ref=current_user.sub,
            revoker_actor_ref=current_user.sub,
            revoker_delegate_ref=None,
            reason_code=payload.reason_code,
        )
    except StrategyTargetApprovalError as error:
        raise _approval_error(error) from None
    return {"approval_ref": approval_ref, "record_version": record_version, "state": "REVOKED"}


@router.post("/submit")
async def submit_approved_target(
    payload: ApprovedTargetSubmitRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: TokenPayload = Depends(
        require_permission(Permission.SUBMIT_APPROVED_STRATEGY_TARGET)
    ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Submit an approved claim using a durable server-generated intent ID."""

    key = _require_idempotency_key(idempotency_key)
    access = _resolve_access(current_user, payload.scope_ref, "approved_target")
    binding = access.approved_target_bindings.get(payload.scope_ref)
    identity = access.application_identity
    if binding is None or identity is None:
        raise _not_configured()
    intent_facts = {
        "operation_kind": "approved_strategy_target",
        "owner_subject": current_user.sub,
        "principal_ref": identity.principal_ref,
        "actor_ref": identity.actor_ref,
        "delegate_ref": identity.delegate_ref,
        "selector_ref": payload.scope_ref,
        "scope_ref": binding.expected_scope_ref,
        "account_ref": binding.account_ref,
        "strategy_ref": binding.strategy_ref,
        "wire_scope": _wire_scope_payload(binding.wire_scope),
        "approval_ref": payload.approval_ref,
        "approval_version": payload.approval_version,
        "target_sha256": payload.target_sha256,
    }
    try:
        claim = await reserve_approved_target_http_operation(
            db,
            owner_subject=current_user.sub,
            principal_ref=identity.principal_ref,
            actor_ref=identity.actor_ref,
            delegate_ref=identity.delegate_ref,
            idempotency_key=key,
            request_sha256=sha256_canonical_json(intent_facts),
            approval_ref=payload.approval_ref,
            approval_version=payload.approval_version,
            target_sha256=payload.target_sha256,
            selector_ref=payload.scope_ref,
            scope_ref=binding.expected_scope_ref,
            account_ref=binding.account_ref,
            strategy_ref=binding.strategy_ref,
        )
    except ApprovedTargetHttpOperationError as error:
        if error.code == "IDEMPOTENCY_CONFLICT":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": error.code, "message": "The operation key is already bound."},
            ) from None
        raise _mapping_error(error) from None

    try:
        reply = await access.worker.submit_approved_target(
            payload.scope_ref,
            {
                "approval_ref": payload.approval_ref,
                "approval_version": payload.approval_version,
                "target_sha256": payload.target_sha256,
                "intent_id": claim.intent_id,
            },
        )
    except ServiceReadUnavailableError as error:
        raise _service_error(error.code) from None
    except Exception as error:  # noqa: BLE001 - no raw exception data leaves HTTP
        del error
        raise _unavailable("APPROVAL_OUTCOME_UNKNOWN") from None

    from app.api.service_orders import _parse_submit_reply

    service_code, record = _parse_submit_reply(reply, claim.intent_id)
    if service_code != "OK":
        raise _execution_error(service_code)
    if record is None:
        raise _unavailable("APPROVAL_OUTCOME_UNKNOWN")
    state = record.get("state")
    outcome = "unknown_review_required" if state == "UNKNOWN" or record.get("review_required") else "durable_record"
    return {
        "operation_kind": "approved_strategy_target",
        "intent_id": claim.intent_id,
        "approval_ref": payload.approval_ref,
        "approval_version": payload.approval_version,
        "target_sha256": payload.target_sha256,
        "service_code": service_code,
        "outcome": outcome,
        "record": dict(record),
        "authority": "Execution journal record; AFI approval is not provider or fill evidence",
    }


def _wire_scope_payload(value: object) -> dict[str, object]:
    fields = (
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
    account_refs = getattr(value, "account_refs", ())
    return {
        name: list(account_refs) if name == "account_refs" else getattr(value, name, None)
        for name in fields
    }


def _require_idempotency_key(value: str | None) -> str:
    if type(value) is not str or not _KEY_RE.fullmatch(value):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "IDEMPOTENCY_KEY_REQUIRED", "message": "A valid Idempotency-Key is required."},
        )
    return value


def _approval_error(error: StrategyTargetApprovalError) -> HTTPException:
    return _map_code(error.code, ambiguous=error.ambiguous)


def _mapping_error(error: ApprovedTargetHttpOperationError) -> HTTPException:
    return _map_code(error.code, ambiguous=error.ambiguous)


def _map_code(code: str, *, ambiguous: bool = False) -> HTTPException:
    if ambiguous or code == "APPROVAL_STORE_UNAVAILABLE":
        return _unavailable("APPROVAL_STORE_UNAVAILABLE")
    if code in {"APPROVAL_NOT_FOUND", "APPROVAL_OWNER_BINDING_MISMATCH"}:
        return _approval_not_found()
    if code in {"APPROVAL_IDENTITY_MISMATCH", "APPROVAL_SCOPE_MISMATCH"}:
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": code, "message": "The approved target is outside this authorized scope."},
        )
    if code == "APPROVAL_TARGET_INVALID":
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"code": code})
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": code, "message": "The approved target is no longer eligible for this operation."},
    )


def _execution_error(code: str) -> HTTPException:
    if code in {"DENIED", "ROLE_NOT_AUTHORIZED", "SCOPE_DENIED", "APPROVAL_REQUIRED"}:
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": code, "message": "Execution denied this approved-target scope."},
        )
    if code in {"NOT_REGISTERED", "CAPABILITY_UNAVAILABLE", "POLICY_REQUIREMENT_UNMET", "STALE_EPOCH"}:
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"code": code})
    if code in {"INVALID_REQUEST", "APPROVAL_TARGET_INVALID"}:
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"code": code})
    if code in {
        "APPROVAL_NOT_FOUND",
        "APPROVAL_OWNER_BINDING_MISMATCH",
        "APPROVAL_IDENTITY_MISMATCH",
        "APPROVAL_SCOPE_MISMATCH",
        "APPROVAL_NOT_APPROVED",
        "APPROVAL_REVOKED",
        "APPROVAL_EXPIRED",
        "APPROVAL_VERSION_MISMATCH",
        "APPROVAL_TARGET_DIGEST_MISMATCH",
        "APPROVAL_POLICY_STALE",
        "APPROVAL_OPERATION_CONFLICT",
        "APPROVAL_CONSUMED_CONFLICT",
        "APPROVAL_NOT_DISPATCHED",
        "APPROVAL_USED_NOT_DISPATCHED",
        "ADMISSION_REQUIRED",
        "INTENT_CONFLICT",
        "STATE_CONFLICT",
    }:
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": code})
    # Includes APPROVAL_STORE_UNAVAILABLE and consume/dispatch unknowns. A
    # caller must inspect the same durable key; this response is not a retry
    # permission or evidence that provider dispatch did not occur.
    return _unavailable(code if code.startswith("APPROVAL_") else "APPROVAL_OUTCOME_UNKNOWN")


def _service_error(code: str) -> HTTPException:
    return _execution_error(code)


def _approval_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "APPROVAL_NOT_FOUND", "message": "The approved target was not found."},
    )


def _not_configured() -> HTTPException:
    return _unavailable("APPROVED_TARGET_NOT_CONFIGURED")


def _unavailable(code: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"code": code, "message": "The approved-target outcome is unavailable; inspect the same operation key."},
    )
