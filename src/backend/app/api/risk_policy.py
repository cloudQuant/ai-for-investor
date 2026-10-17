"""Authenticated control plane for ordinary per-account Risk policies.

Portfolio budget generations use the separate all-member API in
``risk_policy_budget``. These routes bind a policy to one exact account and
manual-book scope and expose only the maker/checker operations granted to the
authenticated subject by the deployment.
"""

from __future__ import annotations

import math
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.afi_owner_scope import require_persisted_human_principal
from app.api.deps import get_current_user, require_permission
from app.api.risk_policy_budget import (
    _catalog_error,
    _error,
    _validate_identifier,
    _worker_unavailable,
)
from app.api.service_read import resolve_risk_account_policy_access
from app.models.permission import Permission
from app.schemas.auth import TokenPayload
from app.services.service_read.access import ReadAccess
from app.services.service_read.client import RiskAccountPolicyBinding

router = APIRouter(
    dependencies=[
        Depends(require_persisted_human_principal),
        Depends(require_permission(Permission.MANAGE_STRATEGY_ORDER_APPROVAL_POLICY)),
    ]
)

_VERSIONED_REFERENCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*-v[1-9][0-9]*$")
_DECIMAL_RE = re.compile(r"^(?:0|[1-9][0-9]*)(?:\.[0-9]{1,18})?$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class AccountPolicyDraftRequest(BaseModel):
    """Strict policy terms; account scope and approval identities are server-owned."""

    model_config = ConfigDict(extra="forbid", strict=True)

    policy_ref: str = Field(min_length=1, max_length=128)
    max_increase_notional: str = Field(min_length=1, max_length=64)
    max_increase_count: int = Field(ge=0, le=1_000_000)
    permit_ttl_seconds: float = Field(gt=0, le=86_400)
    require_strategy_allocation: bool
    notional_unit: str | None = Field(default=None, max_length=32)


def _policy_reference(value: str) -> None:
    if type(value) is not str or _VERSIONED_REFERENCE_RE.fullmatch(value) is None:
        raise _error(
            "VERSIONED_POLICY_REFERENCE_REQUIRED",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Policy references must be immutable versioned identifiers.",
        )


def _binding(
    current_user: TokenPayload, account_ref: str
) -> tuple[ReadAccess, RiskAccountPolicyBinding]:
    _validate_identifier(account_ref, "INVALID_ACCOUNT_REF")
    try:
        access = resolve_risk_account_policy_access(current_user, account_ref)
    except HTTPException:
        raise
    binding = access.risk_account_policy_bindings.get(account_ref)
    identity = access.application_identity
    if (
        binding is None
        or type(getattr(identity, "principal_ref", None)) is not str
        or not identity.principal_ref
        or identity.principal_ref != binding.expected_principal_ref
        or binding.account_ref != account_ref
        or (
            binding.actor_role == "maker"
            and current_user.sub != binding.owner_subject
        )
        or (
            binding.actor_role == "checker"
            and current_user.sub == binding.owner_subject
        )
    ):
        raise _error(
            "RISK_ACCOUNT_POLICY_ACTOR_NOT_AUTHORIZED",
            status.HTTP_403_FORBIDDEN,
            "The authenticated subject is not the configured actor for this account policy role.",
        )
    return access, binding


def _require_operation(binding: RiskAccountPolicyBinding, operation: str) -> None:
    if operation not in binding.operations:
        raise _error(
            "RISK_ACCOUNT_POLICY_ACTOR_NOT_AUTHORIZED",
            status.HTTP_403_FORBIDDEN,
            "The configured account-policy role cannot perform this operation.",
        )


async def _catalog_call(
    access: ReadAccess,
    account_ref: str,
    operation: str,
    arguments: dict[str, object],
) -> dict[str, Any]:
    try:
        reply = await access.worker.call_risk_account_policy(
            account_ref, operation, arguments
        )
    except Exception as error:
        raise _worker_unavailable(error) from None
    if (
        type(reply) is not dict
        or set(reply) != {"ok", "code", "result"}
        or type(reply["ok"]) is not bool
        or type(reply["code"]) is not str
        or type(reply["result"]) is not dict
    ):
        raise _error(
            "INVALID_RISK_POLICY_REPLY",
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "The Risk policy owner returned an invalid reply.",
        )
    if reply["ok"] is not True:
        raise _catalog_error(reply["code"])
    return reply["result"]


def _catalog_result(
    result: dict[str, Any], *, policy_ref: str, states: frozenset[str]
) -> dict[str, Any]:
    if (
        result.get("policy_ref") != policy_ref
        or type(result.get("policy_version")) is not str
        or _SHA256_RE.fullmatch(result["policy_version"]) is None
        or type(result.get("state")) is not str
        or result["state"] not in states
    ):
        raise _error(
            "INVALID_RISK_POLICY_REPLY",
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "The Risk policy owner returned an invalid policy result.",
        )
    return result


@router.post("/accounts/{account_ref}/policies", status_code=201)
async def draft_account_policy(
    account_ref: str,
    request: AccountPolicyDraftRequest,
    current_user: TokenPayload = Depends(get_current_user),
) -> dict[str, Any]:
    access, binding = _binding(current_user, account_ref)
    _require_operation(binding, "policy.draft")
    _policy_reference(request.policy_ref)
    if _DECIMAL_RE.fullmatch(request.max_increase_notional) is None:
        raise _error(
            "INVALID_RISK_POLICY_AMOUNT",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Risk policy limits must be canonical decimal strings.",
        )
    if not math.isfinite(request.permit_ttl_seconds):
        raise _error(
            "INVALID_RISK_POLICY_TTL",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Risk policy permit lifetime must be finite.",
        )
    content = {
        "risk_policy": {
            "policy_id": request.policy_ref,
            "max_increase_notional": request.max_increase_notional,
            "max_increase_count": request.max_increase_count,
            "permit_ttl_seconds": request.permit_ttl_seconds,
            "require_strategy_allocation": request.require_strategy_allocation,
            "notional_unit": request.notional_unit,
        }
    }
    result = await _catalog_call(
        access,
        account_ref,
        "policy.draft",
        {"policy_ref": request.policy_ref, "content": content},
    )
    result = _catalog_result(
        result,
        policy_ref=request.policy_ref,
        states=frozenset({"draft", "approved", "published"}),
    )
    return {
        "account_ref": account_ref,
        "policy_ref": request.policy_ref,
        "policy_version": result["policy_version"],
        "state": result["state"],
    }


@router.post("/accounts/{account_ref}/policies/{policy_ref}/approve")
async def approve_account_policy(
    account_ref: str,
    policy_ref: str,
    current_user: TokenPayload = Depends(get_current_user),
) -> dict[str, Any]:
    access, binding = _binding(current_user, account_ref)
    _require_operation(binding, "policy.approve")
    _policy_reference(policy_ref)
    result = _catalog_result(
        await _catalog_call(
            access, account_ref, "policy.approve", {"policy_ref": policy_ref}
        ),
        policy_ref=policy_ref,
        states=frozenset({"approved"}),
    )
    return {
        "account_ref": account_ref,
        "policy_ref": policy_ref,
        "policy_version": result["policy_version"],
        "state": result["state"],
    }


@router.post("/accounts/{account_ref}/policies/{policy_ref}/publish")
async def publish_account_policy(
    account_ref: str,
    policy_ref: str,
    current_user: TokenPayload = Depends(get_current_user),
) -> dict[str, Any]:
    access, binding = _binding(current_user, account_ref)
    _require_operation(binding, "policy.publish")
    _policy_reference(policy_ref)
    result = await _catalog_call(
        access, account_ref, "policy.publish", {"policy_ref": policy_ref}
    )
    if (
        result.get("policy_ref") != policy_ref
        or type(result.get("policy_version")) is not str
        or _SHA256_RE.fullmatch(result["policy_version"]) is None
        or type(result.get("published_utc")) is not str
        or not result["published_utc"]
    ):
        raise _error(
            "INVALID_RISK_POLICY_REPLY",
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "The Risk policy owner returned an invalid publication receipt.",
        )
    return {
        "account_ref": account_ref,
        "policy_ref": policy_ref,
        "policy_version": result["policy_version"],
        "state": "published",
        "published_utc": result["published_utc"],
    }


@router.get("/accounts/{account_ref}/policies/{policy_ref}")
async def read_account_policy(
    account_ref: str,
    policy_ref: str,
    current_user: TokenPayload = Depends(get_current_user),
) -> dict[str, Any]:
    access, binding = _binding(current_user, account_ref)
    _require_operation(binding, "policy.inspect")
    _require_operation(binding, "policy.confirmation.read")
    _policy_reference(policy_ref)
    result = _catalog_result(
        await _catalog_call(
            access, account_ref, "policy.inspect", {"policy_ref": policy_ref}
        ),
        policy_ref=policy_ref,
        states=frozenset({"draft", "approved", "published"}),
    )
    content = result.get("content")
    if type(content) is not dict or set(content) != {"risk_policy"}:
        raise _error(
            "INVALID_RISK_POLICY_REPLY",
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "The Risk policy owner returned an invalid policy document.",
        )
    confirmation = await _catalog_call(
        access,
        account_ref,
        "policy.confirmation.read",
        {"policy_ref": policy_ref},
    )
    if (
        confirmation.get("policy_ref") != policy_ref
        or type(confirmation.get("owner_confirmed")) is not bool
        or type(confirmation.get("document_available")) is not bool
        or (
            confirmation["owner_confirmed"]
            and (
                type(confirmation.get("policy_version")) is not str
                or _SHA256_RE.fullmatch(confirmation["policy_version"]) is None
                or type(confirmation.get("confirmed_utc")) is not str
                or not confirmation["confirmed_utc"]
            )
        )
        or (
            not confirmation["owner_confirmed"]
            and (
                confirmation.get("policy_version") is not None
                or confirmation.get("confirmed_utc") is not None
                or confirmation["document_available"]
            )
        )
        or (
            confirmation["owner_confirmed"]
            and confirmation["policy_version"] != result["policy_version"]
        )
    ):
        raise _error(
            "POLICY_CONFIRMATION_VERSION_MISMATCH",
            status.HTTP_409_CONFLICT,
            "The stored owner confirmation does not match this exact policy version.",
        )
    return {
        "account_ref": account_ref,
        "policy_ref": policy_ref,
        "policy_version": result["policy_version"],
        "state": result["state"],
        "risk_policy": content["risk_policy"],
        "owner_confirmed": confirmation["owner_confirmed"],
        "owner_confirmed_version": confirmation["policy_version"],
        "owner_confirmed_utc": confirmation["confirmed_utc"],
        "owner_document_available": confirmation["document_available"],
    }
