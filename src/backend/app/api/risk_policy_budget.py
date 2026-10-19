"""Authenticated control-plane routes for Risk-owned portfolio budgets.

The Risk policy catalog remains the only budget authority.  This API validates
an immutable live portfolio membership, compiles exact member drafts, and
forwards typed operations through the subject's configured ServiceRead worker.
It never accepts a caller-supplied owner scope, publication receipt, pool
capacity, or consumer-effective flag.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.afi_owner_scope import require_persisted_human_principal
from app.api.deps import get_current_user, require_permission
from app.api.service_read import resolve_risk_policy_budget_access
from app.db.database import get_db
from app.models.permission import Permission
from app.models.portfolio_composition import PortfolioCompositionVersion
from app.schemas.auth import TokenPayload
from app.services.portfolio_composition import PortfolioCompositionService
from app.services.risk_policy_budget import (
    AccountBudgetAllocation,
    RiskPolicyBudgetError,
    StaticPortfolioBudgetPlan,
    compile_static_portfolio_budget,
)
from app.services.service_read.access import ReadAccess
from app.services.service_read.client import ServiceReadUnavailableError

logger = logging.getLogger(__name__)

router = APIRouter(
    dependencies=[
        Depends(require_persisted_human_principal),
        Depends(require_permission(Permission.MANAGE_STRATEGY_ORDER_APPROVAL_POLICY)),
    ]
)

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_VERSIONED_IDENTIFIER_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._:-]*-v[1-9][0-9]*$"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_DECIMAL_RE = re.compile(r"^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")
_MAX_MEMBERS = 256
_BUDGET_GENERATION_STATES = frozenset(
    {
        "proposed",
        "approved",
        "publishing",
        "partial_hold",
        "unknown_hold",
        "authority_ready",
        "rejected",
        "retracted",
    }
)
_BUDGET_MEMBER_STATES = frozenset(
    {"pending", "published", "confirmed", "rejected", "unknown"}
)


class BudgetAllocationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    account_ref: str = Field(min_length=1, max_length=128)
    amount: str = Field(min_length=1, max_length=64)
    currency: str = Field(min_length=3, max_length=3)
    metric: str = Field(default="max_increase_notional", min_length=1, max_length=64)
    max_increase_count: int = Field(default=1, ge=0, le=1_000_000)


class BudgetFxObservationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    observation_ref: str = Field(min_length=1, max_length=128)
    base_currency: str = Field(min_length=3, max_length=3)
    quote_currency: str = Field(min_length=3, max_length=3)
    direction: str = Field(min_length=1, max_length=32)
    rate_unit: str = Field(min_length=1, max_length=32)
    rate: str = Field(min_length=1, max_length=64)
    as_of_ns: int = Field(gt=0)
    valid_until_ns: int = Field(gt=0)
    source_ref: str = Field(min_length=1, max_length=128)
    source_version: str = Field(min_length=1, max_length=128)
    source_generation: str = Field(min_length=1, max_length=128)
    source_cursor: str = Field(min_length=1, max_length=128)


class BudgetPlanRequest(BaseModel):
    """Client terms only; scope, roster and pool authority are server-owned."""

    model_config = ConfigDict(extra="forbid", strict=True)

    membership_version: int = Field(ge=1)
    membership_sha256: str = Field(min_length=64, max_length=64)
    currency: str = Field(min_length=3, max_length=3)
    total_amount: str = Field(min_length=1, max_length=64)
    unallocated_amount: str = Field(min_length=1, max_length=64)
    allocations: list[BudgetAllocationRequest] = Field(min_length=1, max_length=_MAX_MEMBERS)
    fx_observations: list[BudgetFxObservationRequest] = Field(
        default_factory=list, max_length=_MAX_MEMBERS
    )


class GenerationActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


def _error(code: str, http_status: int, message: str) -> HTTPException:
    return HTTPException(
        status_code=http_status,
        detail={"code": code, "message": message},
    )


def _validate_identifier(value: str, code: str) -> None:
    if type(value) is not str or _IDENTIFIER_RE.fullmatch(value) is None:
        raise _error(code, status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid identifier.")


def _validate_generation_ref(value: str) -> None:
    if (
        type(value) is not str
        or len(value) > 128
        or _IDENTIFIER_RE.fullmatch(value) is None
        or _VERSIONED_IDENTIFIER_RE.fullmatch(value) is None
    ):
        raise _error(
            "VERSIONED_GENERATION_REF_REQUIRED",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Generation references must be versioned identifiers.",
        )


def _policy_ref_for_generation(generation_ref: str, account_ref: str) -> str:
    """Derive one stable policy reference from the durable operation ID."""

    payload = json.dumps(
        [generation_ref, account_ref],
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("ascii")
    digest = hashlib.sha256(payload).hexdigest()
    return f"afi-budget-{digest}-v1"


def _catalog_error(code: str) -> HTTPException:
    if code in {
        "BUDGET_GENERATION_NOT_FOUND",
        "BUDGET_MEMBER_NOT_FOUND",
        "POLICY_NOT_FOUND",
    }:
        http_status = status.HTTP_404_NOT_FOUND
    elif code in {
        "APPROVER_NOT_AUTHORIZED",
        "APPROVER_MUST_DIFFER_FROM_OWNER",
        "APPROVAL_NOT_AUTHORIZED",
        "POLICY_PUBLISH_NOT_AUTHORIZED",
        "BUDGET_PUBLISH_NOT_AUTHORIZED",
        "BUDGET_PROPOSAL_OWNER_REQUIRED",
        "BUDGET_MEMBER_OWNER_REQUIRED",
        "SCOPE_NOT_OWNER",
        "BUDGET_MEMBER_SCOPE_MISMATCH",
    }:
        http_status = status.HTTP_403_FORBIDDEN
    elif code in {
        "CATALOG_STORAGE_UNAVAILABLE",
        "BUDGET_FX_AUTHORITY_UNAVAILABLE",
        "BUDGET_FX_SOURCE_UNAVAILABLE",
        "CONFIRMATION_STORE_UNAVAILABLE",
    }:
        http_status = status.HTTP_503_SERVICE_UNAVAILABLE
    elif code.startswith("INVALID_") or code in {
        "UNSUPPORTED_BUDGET_METRIC",
        "MIXED_BUDGET_METRIC",
        "BUDGET_NOT_CONSERVED",
        "NON_TERMINATING_BUDGET_FX_RESULT",
    }:
        http_status = status.HTTP_422_UNPROCESSABLE_ENTITY
    else:
        http_status = status.HTTP_409_CONFLICT
    return _error(code, http_status, "The Risk policy catalog refused this operation.")


def _worker_unavailable(error: BaseException) -> HTTPException:
    code = getattr(error, "code", None)
    if type(code) is not str or _IDENTIFIER_RE.fullmatch(code) is None:
        code = "SERVICE_READ_FAILED"
        logger.warning("Risk policy budget worker failed: %s", type(error).__name__)
    return _error(
        code,
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "The configured Risk policy owner did not return a confirmed reply.",
    )


def _binding(
    current_user: TokenPayload, portfolio_ref: str
) -> tuple[ReadAccess, Any]:
    _validate_identifier(portfolio_ref, "INVALID_PORTFOLIO_REF")
    try:
        access = resolve_risk_policy_budget_access(current_user, portfolio_ref)
    except HTTPException:
        raise
    binding = access.risk_policy_budget_bindings.get(portfolio_ref)
    identity = access.application_identity
    if (
        binding is None
        or type(getattr(identity, "principal_ref", None)) is not str
        or not getattr(identity, "principal_ref", "")
    ):
        raise _error(
            "RISK_POLICY_BUDGET_NOT_CONFIGURED",
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "This portfolio has no configured Risk policy owner.",
        )
    expected_principal = getattr(binding, "expected_principal_ref", None)
    owner_subject = getattr(binding, "owner_subject", None)
    if (
        (expected_principal is not None and expected_principal != identity.principal_ref)
        or (
            owner_subject is not None
            and binding.actor_role == "maker"
            and current_user.sub != owner_subject
        )
        or (
            owner_subject is not None
            and binding.actor_role == "checker"
            and current_user.sub == owner_subject
        )
    ):
        raise _error(
            "RISK_POLICY_BUDGET_ACTOR_NOT_AUTHORIZED",
            status.HTTP_403_FORBIDDEN,
            "The authenticated subject is not the configured actor for this budget role.",
        )
    return access, binding


def _require_budget_operation(binding: Any, operation: str) -> None:
    operations = getattr(binding, "operations", frozenset())
    if operation not in operations:
        raise _error(
            "RISK_POLICY_BUDGET_ACTOR_NOT_AUTHORIZED",
            status.HTTP_403_FORBIDDEN,
            "The configured budget role cannot perform this operation.",
        )


async def _latest_live_membership(
    db: AsyncSession,
    *,
    owner_subject: str,
    portfolio_ref: str,
    expected_version: int | None = None,
    expected_sha256: str | None = None,
) -> tuple[PortfolioCompositionVersion, tuple[str, ...]]:
    try:
        latest_version = await db.scalar(
            select(func.max(PortfolioCompositionVersion.membership_version)).where(
                PortfolioCompositionVersion.owner_subject == owner_subject,
                PortfolioCompositionVersion.portfolio_ref == portfolio_ref,
            )
        )
    except SQLAlchemyError:
        raise _error(
            "PORTFOLIO_MEMBERSHIP_UNAVAILABLE",
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "The current portfolio membership could not be read.",
        ) from None
    if type(latest_version) is not int:
        raise _error(
            "PORTFOLIO_COMPOSITION_NOT_FOUND",
            status.HTTP_404_NOT_FOUND,
            "No portfolio membership is available.",
        )
    row = await PortfolioCompositionService(db).get_version(
        owner_subject, portfolio_ref, latest_version
    )
    if row.source_type != "live":
        raise _error(
            "LIVE_PORTFOLIO_MEMBERSHIP_REQUIRED",
            status.HTTP_409_CONFLICT,
            "Static Risk budgets require a live account membership.",
        )
    if type(row.members) is not list or any(
        type(member) is not dict
        or set(member) != {"kind", "ref"}
        or type(member["kind"]) is not str
        or type(member["ref"]) is not str
        or not member["ref"]
        or member["ref"] != member["ref"].strip()
        for member in row.members
    ):
        raise _error(
            "INVALID_PORTFOLIO_MEMBERSHIP",
            status.HTTP_409_CONFLICT,
            "The stored portfolio membership is malformed.",
        )
    if any(member["kind"] not in {"account", "strategy"} for member in row.members):
        raise _error(
            "INVALID_PORTFOLIO_MEMBERSHIP",
            status.HTTP_409_CONFLICT,
            "The live portfolio membership contains an unsupported member type.",
        )
    account_refs = tuple(
        sorted(member["ref"] for member in row.members if member["kind"] == "account")
    )
    if (
        not account_refs
        or len(account_refs) > _MAX_MEMBERS
        or len(set(account_refs)) != len(account_refs)
    ):
        raise _error(
            "INVALID_PORTFOLIO_ACCOUNT_MEMBERS",
            status.HTTP_409_CONFLICT,
            "The live membership has no unique supported account roster.",
        )
    if expected_version is not None and (
        row.membership_version != expected_version
        or row.membership_sha256 != expected_sha256
    ):
        raise _error(
            "STALE_PORTFOLIO_MEMBERSHIP",
            status.HTTP_409_CONFLICT,
            "The proposal does not match the current live membership version.",
        )
    return row, account_refs


async def _assert_binding_roster(
    db: AsyncSession,
    *,
    current_user: TokenPayload,
    portfolio_ref: str,
    binding: Any,
    expected_version: int | None = None,
    expected_sha256: str | None = None,
) -> tuple[PortfolioCompositionVersion, tuple[str, ...]]:
    row, account_refs = await _latest_live_membership(
        db,
        owner_subject=getattr(binding, "owner_subject", None) or current_user.sub,
        portfolio_ref=portfolio_ref,
        expected_version=expected_version,
        expected_sha256=expected_sha256,
    )
    if set(account_refs) != set(binding.member_scope_refs):
        raise _error(
            "RISK_POLICY_MEMBER_ROSTER_MISMATCH",
            status.HTTP_409_CONFLICT,
            "The configured Risk member scopes do not match this portfolio version.",
        )
    return row, account_refs


async def _catalog_call(
    access: ReadAccess,
    portfolio_ref: str,
    operation: str,
    arguments: dict[str, object],
    *,
    member_account_ref: str | None = None,
) -> dict[str, Any]:
    try:
        reply = await access.worker.call_risk_policy_budget(
            portfolio_ref,
            operation,
            arguments,
            member_account_ref=member_account_ref,
        )
    except ServiceReadUnavailableError as error:
        raise _worker_unavailable(error) from None
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


def _plan_objects(
    portfolio_ref: str,
    membership: PortfolioCompositionVersion,
    request: BudgetPlanRequest,
    *,
    generation_ref: str,
) -> tuple[Any, tuple[dict[str, object], ...]]:
    if request.currency != membership.base_currency:
        raise _error(
            "BUDGET_CURRENCY_MUST_MATCH_PORTFOLIO_BASE",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "The valuation currency must match the portfolio base currency.",
        )
    if _SHA256_RE.fullmatch(request.membership_sha256) is None:
        raise _error(
            "INVALID_MEMBERSHIP_DIGEST",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "The membership digest is invalid.",
        )
    policy_refs: dict[str, str] = {}
    allocations: list[AccountBudgetAllocation] = []
    for item in request.allocations:
        _validate_identifier(item.account_ref, "INVALID_ACCOUNT_REF")
        policy_refs[item.account_ref] = _policy_ref_for_generation(
            generation_ref, item.account_ref
        )
        if _DECIMAL_RE.fullmatch(item.amount) is None:
            raise _error(
                "INVALID_BUDGET_AMOUNT",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Amounts must be canonical decimal strings.",
            )
        try:
            amount = Decimal(item.amount)
        except InvalidOperation:
            raise _error(
                "INVALID_BUDGET_AMOUNT",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Amounts must be canonical decimal strings.",
            ) from None
        allocations.append(
            AccountBudgetAllocation(
                account_ref=item.account_ref,
                amount=amount,
                currency=item.currency,
                metric=item.metric,
                max_increase_count=item.max_increase_count,
            )
        )
    if (
        _DECIMAL_RE.fullmatch(request.total_amount) is None
        or _DECIMAL_RE.fullmatch(request.unallocated_amount) is None
    ):
        raise _error(
            "INVALID_BUDGET_AMOUNT",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Amounts must be canonical decimal strings.",
        )
    if any(_DECIMAL_RE.fullmatch(item.rate) is None for item in request.fx_observations):
        raise _error(
            "INVALID_BUDGET_FX_RATE",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "FX rates must be canonical decimal strings.",
        )
    try:
        total_amount = Decimal(request.total_amount)
        unallocated_amount = Decimal(request.unallocated_amount)
        observations: dict[str, Any] = {}
        if request.fx_observations:
            from bt_api_risk.portfolio_analytics import FxObservationV1

            for item in request.fx_observations:
                if item.base_currency in observations:
                    raise RiskPolicyBudgetError("DUPLICATE_BUDGET_FX_FACT")
                observations[item.base_currency] = FxObservationV1(
                    observation_ref=item.observation_ref,
                    base_currency=item.base_currency,
                    quote_currency=item.quote_currency,
                    direction=item.direction,
                    rate_unit=item.rate_unit,
                    rate=Decimal(item.rate),
                    as_of_ns=item.as_of_ns,
                    valid_until_ns=item.valid_until_ns,
                    source_ref=item.source_ref,
                    source_version=item.source_version,
                    source_generation=item.source_generation,
                    source_cursor=item.source_cursor,
                )
        plan = StaticPortfolioBudgetPlan(
            portfolio_ref=portfolio_ref,
            membership_version=request.membership_version,
            membership_sha256=request.membership_sha256,
            currency=request.currency,
            total_amount=total_amount,
            unallocated_amount=unallocated_amount,
            allocations=tuple(allocations),
        )
        compiled = compile_static_portfolio_budget(
            plan,
            policy_refs=policy_refs,
            fx_observations=observations,
        )
    except RiskPolicyBudgetError as error:
        raise _error(
            error.code,
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "The static budget terms or FX observations are invalid.",
        ) from None
    except (InvalidOperation, ValueError, TypeError):
        raise _error(
            "INVALID_BUDGET_FX_FACTS",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "The supplied FX observation facts are invalid.",
        ) from None
    return compiled, compiled.catalog_requests()


def _budget_proposal(
    *, pool_ref: str, generation_ref: str, compiled: Any, catalog_requests: tuple[dict[str, object], ...]
) -> dict[str, object]:
    allocations: list[dict[str, object]] = []
    for request in catalog_requests:
        content = request.get("content")
        if type(content) is not dict or type(content.get("afi_budget")) is not dict:
            raise _error(
                "INVALID_COMPILED_BUDGET",
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "The budget compiler returned an invalid proposal.",
            )
        budget = content["afi_budget"]
        allocations.append(
            {
                "account_ref": budget["account_ref"],
                "policy_ref": request["policy_ref"],
                "amount": budget["allocated_amount"],
                "max_increase_count": content["risk_policy"]["max_increase_count"],
                "metric": budget["metric"],
                "currency": budget["currency"],
                "source_amount": budget["source_amount"],
                "source_currency": budget["source_currency"],
                "fx_observation": budget["fx_observation"],
            }
        )
    return {
        "pool_ref": pool_ref,
        "generation_ref": generation_ref,
        "portfolio_ref": compiled.portfolio_ref,
        "membership_version": compiled.membership_version,
        "membership_sha256": _compiled_membership_digest(catalog_requests),
        "allocation_set_sha256": compiled.allocation_set_sha256,
        "currency": compiled.currency,
        "metric": compiled.metric,
        "total_amount": compiled.total_amount,
        "unallocated_amount": compiled.unallocated_amount,
        "allocations": allocations,
    }


def _compiled_membership_digest(catalog_requests: tuple[dict[str, object], ...]) -> str:
    first = catalog_requests[0]["content"]["afi_budget"]
    return str(first["membership_sha256"])


def _generation_view(
    result: dict[str, Any],
    *,
    latest_membership: PortfolioCompositionVersion | None = None,
) -> dict[str, Any]:
    state = result.get("state")
    if type(state) is not str or state not in _BUDGET_GENERATION_STATES:
        raise _error(
            "INVALID_RISK_POLICY_REPLY",
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "The Risk policy owner returned an invalid generation.",
        )
    view = dict(result)
    view["authority_ready"] = state == "authority_ready"
    view["consumer_effective"] = False
    view["consumer_status"] = (
        "awaiting_account_gate_binding"
        if state == "authority_ready"
        else "not_authority_ready"
    )
    if latest_membership is not None:
        view["membership_current"] = (
            result.get("membership_version") == latest_membership.membership_version
            and result.get("membership_sha256") == latest_membership.membership_sha256
        )
    return view


async def _read_generation(
    access: ReadAccess,
    binding: Any,
    portfolio_ref: str,
    generation_ref: str,
) -> dict[str, Any]:
    _validate_generation_ref(generation_ref)
    result = await _catalog_call(
        access,
        portfolio_ref,
        "policy.budget.read",
        {"generation_ref": generation_ref},
    )
    if (
        result.get("generation_ref") != generation_ref
        or result.get("portfolio_ref") != portfolio_ref
        or result.get("pool_ref") != binding.pool_ref
        or type(result.get("membership_version")) is not int
        or result["membership_version"] < 1
        or type(result.get("membership_sha256")) is not str
        or _SHA256_RE.fullmatch(result["membership_sha256"]) is None
        or type(result.get("allocation_set_sha256")) is not str
        or _SHA256_RE.fullmatch(result["allocation_set_sha256"]) is None
        or type(result.get("currency")) is not str
        or re.fullmatch(r"[A-Z]{3}", result["currency"]) is None
        or result.get("metric") != "max_increase_notional"
        or type(result.get("state")) is not str
        or result.get("state") not in _BUDGET_GENERATION_STATES
    ):
        raise _error(
            "RISK_POLICY_SCOPE_MISMATCH",
            status.HTTP_403_FORBIDDEN,
            "The generation is outside this configured portfolio scope.",
        )
    members = result.get("members")
    expected_accounts = set(binding.member_scope_refs)
    expected_member_fields = {
        "account_ref",
        "policy_ref",
        "amount",
        "policy_version",
        "state",
    }
    if (
        type(members) not in (list, tuple)
        or len(members) != len(expected_accounts)
        or any(
            type(member) is not dict
            or set(member) != expected_member_fields
            or type(member["account_ref"]) is not str
            or type(member["policy_ref"]) is not str
            or type(member["amount"]) is not str
            or type(member["policy_version"]) is not str
            or _VERSIONED_IDENTIFIER_RE.fullmatch(member["policy_ref"]) is None
            or len(member["policy_ref"]) > 128
            or _SHA256_RE.fullmatch(member["policy_version"]) is None
            or _DECIMAL_RE.fullmatch(member["amount"]) is None
            or type(member["state"]) is not str
            or member["state"] not in _BUDGET_MEMBER_STATES
            for member in members
        )
        or {member["account_ref"] for member in members} != expected_accounts
        or len({member["account_ref"] for member in members}) != len(members)
    ):
        raise _error(
            "RISK_POLICY_MEMBER_ROSTER_MISMATCH",
            status.HTTP_409_CONFLICT,
            "The generation member set does not match configured account scopes.",
        )
    return result


async def _require_current_generation_membership(
    db: AsyncSession,
    current_user: TokenPayload,
    portfolio_ref: str,
    binding: Any,
    result: dict[str, Any],
) -> PortfolioCompositionVersion:
    row, _ = await _assert_binding_roster(
        db,
        current_user=current_user,
        portfolio_ref=portfolio_ref,
        binding=binding,
    )
    if (
        result.get("membership_version") != row.membership_version
        or result.get("membership_sha256") != row.membership_sha256
    ):
        raise _error(
            "STALE_PORTFOLIO_MEMBERSHIP",
            status.HTTP_409_CONFLICT,
            "The generation no longer matches the current live membership.",
        )
    return row


@router.post("/{portfolio_ref}/generations/{generation_ref}/drafts")
async def draft_budget_generation_members(
    portfolio_ref: str,
    generation_ref: str,
    request: BudgetPlanRequest,
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Create/replay each immutable account draft for one generation ID.

    Calls are one account at a time on the Risk owner thread.  The catalog's
    exact-request replay lets a caller retry the same generation and payload
    after an interrupted HTTP response; changed terms or identity conflict.
    """

    access, binding = _binding(current_user, portfolio_ref)
    _require_budget_operation(binding, "policy.draft")
    _validate_generation_ref(generation_ref)
    membership, account_refs = await _assert_binding_roster(
        db,
        current_user=current_user,
        portfolio_ref=portfolio_ref,
        binding=binding,
        expected_version=request.membership_version,
        expected_sha256=request.membership_sha256,
    )
    compiled, catalog_requests = _plan_objects(
        portfolio_ref, membership, request, generation_ref=generation_ref
    )
    if {draft.account_ref for draft in compiled.drafts} != set(account_refs):
        raise _error(
            "BUDGET_ALLOCATION_ROSTER_MISMATCH",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Every current account member needs exactly one allocation.",
        )
    completed: list[dict[str, object]] = []
    for draft_request in catalog_requests:
        content = draft_request["content"]
        assert type(content) is dict
        budget = content["afi_budget"]
        account_ref = str(budget["account_ref"])
        try:
            result = await _catalog_call(
                access,
                portfolio_ref,
                "policy.draft",
                draft_request,
                member_account_ref=account_ref,
            )
        except HTTPException as error:
            if error.status_code == status.HTTP_503_SERVICE_UNAVAILABLE:
                raise _error(
                    "BUDGET_DRAFT_REPLY_UNKNOWN",
                    status.HTTP_503_SERVICE_UNAVAILABLE,
                    "Retry this same generation ID and exact plan; Risk may have committed the current draft.",
                ) from None
            raise
        if (
            result.get("policy_ref") != draft_request.get("policy_ref")
            or type(result.get("policy_version")) is not str
            or _SHA256_RE.fullmatch(result["policy_version"]) is None
            or result.get("state") not in {"draft", "approved", "published"}
        ):
            raise _error(
                "INVALID_RISK_POLICY_REPLY",
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "The Risk policy owner returned an invalid draft receipt.",
            )
        completed.append(
            {
                "account_ref": account_ref,
                "policy_ref": result["policy_ref"],
                "policy_version": result["policy_version"],
                "state": result["state"],
            }
        )
    return {
        "generation_ref": generation_ref,
        "portfolio_ref": portfolio_ref,
        "membership_version": membership.membership_version,
        "membership_sha256": membership.membership_sha256,
        "allocation_set_sha256": compiled.allocation_set_sha256,
        "members": completed,
        "state": "drafts_ready",
        "consumer_effective": False,
    }


@router.post("/{portfolio_ref}/generations/{generation_ref}/propose")
async def propose_budget_generation(
    portfolio_ref: str,
    generation_ref: str,
    request: BudgetPlanRequest,
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Reserve a complete compiled allocation in the single Risk authority."""

    access, binding = _binding(current_user, portfolio_ref)
    _require_budget_operation(binding, "policy.budget.propose")
    _validate_generation_ref(generation_ref)
    membership, account_refs = await _assert_binding_roster(
        db,
        current_user=current_user,
        portfolio_ref=portfolio_ref,
        binding=binding,
        expected_version=request.membership_version,
        expected_sha256=request.membership_sha256,
    )
    compiled, catalog_requests = _plan_objects(
        portfolio_ref, membership, request, generation_ref=generation_ref
    )
    if {draft.account_ref for draft in compiled.drafts} != set(account_refs):
        raise _error(
            "BUDGET_ALLOCATION_ROSTER_MISMATCH",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Every current account member needs exactly one allocation.",
        )
    proposal = _budget_proposal(
        pool_ref=binding.pool_ref,
        generation_ref=generation_ref,
        compiled=compiled,
        catalog_requests=catalog_requests,
    )
    result = await _catalog_call(
        access, portfolio_ref, "policy.budget.propose", proposal
    )
    view = _generation_view(result, latest_membership=membership)
    return view


@router.get("/{portfolio_ref}/generations/{generation_ref}")
async def read_budget_generation(
    portfolio_ref: str,
    generation_ref: str,
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    access, binding = _binding(current_user, portfolio_ref)
    _require_budget_operation(binding, "policy.budget.read")
    result = await _read_generation(access, binding, portfolio_ref, generation_ref)
    latest = None
    try:
        latest, _ = await _assert_binding_roster(
            db,
            current_user=current_user,
            portfolio_ref=portfolio_ref,
            binding=binding,
        )
    except HTTPException as error:
        if error.status_code not in {
            status.HTTP_404_NOT_FOUND,
            status.HTTP_409_CONFLICT,
        }:
            raise
    return _generation_view(result, latest_membership=latest)


@router.post("/{portfolio_ref}/generations/{generation_ref}/approve")
async def approve_budget_generation(
    portfolio_ref: str,
    generation_ref: str,
    _: GenerationActionRequest,
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    access, binding = _binding(current_user, portfolio_ref)
    _require_budget_operation(binding, "policy.budget.approve")
    current = await _read_generation(access, binding, portfolio_ref, generation_ref)
    membership = await _require_current_generation_membership(
        db, current_user, portfolio_ref, binding, current
    )
    await _catalog_call(
        access,
        portfolio_ref,
        "policy.budget.approve",
        {"generation_ref": generation_ref},
    )
    current = await _read_generation(access, binding, portfolio_ref, generation_ref)
    return _generation_view(current, latest_membership=membership)


@router.post("/{portfolio_ref}/generations/{generation_ref}/members/{account_ref}/publish")
async def publish_budget_member(
    portfolio_ref: str,
    generation_ref: str,
    account_ref: str,
    _: GenerationActionRequest,
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    access, binding = _binding(current_user, portfolio_ref)
    _require_budget_operation(binding, "policy.budget.publish_member")
    _validate_identifier(account_ref, "INVALID_ACCOUNT_REF")
    current = await _read_generation(access, binding, portfolio_ref, generation_ref)
    membership = await _require_current_generation_membership(
        db, current_user, portfolio_ref, binding, current
    )
    await _catalog_call(
        access,
        portfolio_ref,
        "policy.budget.publish_member",
        {"generation_ref": generation_ref, "account_ref": account_ref},
    )
    current = await _read_generation(access, binding, portfolio_ref, generation_ref)
    view = _generation_view(current, latest_membership=membership)
    view["member_account_ref"] = account_ref
    return view


@router.post("/{portfolio_ref}/generations/{generation_ref}/members/{account_ref}/confirm")
async def confirm_budget_member(
    portfolio_ref: str,
    generation_ref: str,
    account_ref: str,
    _: GenerationActionRequest,
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    access, binding = _binding(current_user, portfolio_ref)
    _require_budget_operation(binding, "policy.budget.owner_confirm_member")
    _validate_identifier(account_ref, "INVALID_ACCOUNT_REF")
    current = await _read_generation(access, binding, portfolio_ref, generation_ref)
    membership = await _require_current_generation_membership(
        db, current_user, portfolio_ref, binding, current
    )
    result = await _catalog_call(
        access,
        portfolio_ref,
        "policy.budget.owner_confirm_member",
        {"generation_ref": generation_ref, "account_ref": account_ref},
        member_account_ref=account_ref,
    )
    current = await _read_generation(access, binding, portfolio_ref, generation_ref)
    return _generation_view(current, latest_membership=membership)


@router.post("/{portfolio_ref}/generations/{generation_ref}/members/{account_ref}/reject")
async def reject_budget_member(
    portfolio_ref: str,
    generation_ref: str,
    account_ref: str,
    _: GenerationActionRequest,
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    access, binding = _binding(current_user, portfolio_ref)
    _require_budget_operation(binding, "policy.budget.reject_member")
    _validate_identifier(account_ref, "INVALID_ACCOUNT_REF")
    current = await _read_generation(access, binding, portfolio_ref, generation_ref)
    membership = await _require_current_generation_membership(
        db, current_user, portfolio_ref, binding, current
    )
    await _read_generation(access, binding, portfolio_ref, generation_ref)
    await _catalog_call(
        access,
        portfolio_ref,
        "policy.budget.reject_member",
        {"generation_ref": generation_ref, "account_ref": account_ref},
        member_account_ref=account_ref,
    )
    current = await _read_generation(access, binding, portfolio_ref, generation_ref)
    return _generation_view(current, latest_membership=membership)


@router.post("/{portfolio_ref}/generations/{generation_ref}/mark-unknown")
async def mark_budget_generation_unknown(
    portfolio_ref: str,
    generation_ref: str,
    _: GenerationActionRequest,
    current_user: TokenPayload = Depends(get_current_user),
) -> dict[str, Any]:
    access, binding = _binding(current_user, portfolio_ref)
    _require_budget_operation(binding, "policy.budget.mark_unknown")
    await _read_generation(access, binding, portfolio_ref, generation_ref)
    await _catalog_call(
        access,
        portfolio_ref,
        "policy.budget.mark_unknown",
        {"generation_ref": generation_ref},
    )
    current = await _read_generation(access, binding, portfolio_ref, generation_ref)
    return _generation_view(current)


@router.post("/{portfolio_ref}/generations/{generation_ref}/retract")
async def retract_budget_generation(
    portfolio_ref: str,
    generation_ref: str,
    _: GenerationActionRequest,
    current_user: TokenPayload = Depends(get_current_user),
) -> dict[str, Any]:
    access, binding = _binding(current_user, portfolio_ref)
    _require_budget_operation(binding, "policy.budget.retract")
    await _read_generation(access, binding, portfolio_ref, generation_ref)
    await _catalog_call(
        access,
        portfolio_ref,
        "policy.budget.retract",
        {"generation_ref": generation_ref},
    )
    current = await _read_generation(access, binding, portfolio_ref, generation_ref)
    return _generation_view(current)
