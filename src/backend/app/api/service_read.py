"""Read-only application endpoints backed by the shared service packages.

The endpoints report what the authorized read path can prove and nothing more:
a value is returned only with its quality marker, an unreadable service answers
with an explicit unavailable status instead of a placeholder balance, and a
refused scope is a refusal rather than a degraded page.  Nothing here connects
to a provider, so opening the page never logs an account in.

The composition root installs the trusted subject-to-worker directory with
:func:`configure_service_read`. Without it the endpoints report
``not_configured``; they never construct a runtime on their own.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.afi_owner_scope import require_persisted_owner_scope
from app.api.deps import get_current_user
from app.schemas.auth import TokenPayload
from app.services.service_read.access import (
    ReadAccess,
    ServiceReadAccessDirectory,
    ServiceReadAccessError,
)
from app.services.service_read.client import ServiceReadUnavailableError
from app.services.service_read.consumers import CONSUMERS, validate_consumers
from app.services.service_read.contracts import (
    AccountReadView,
    OrderReadView,
    StrategyHealthView,
)

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_persisted_owner_scope)])

_access_directory: ServiceReadAccessDirectory | None = None

#: Refusals that must not be presented as a degraded page.
_FORBIDDEN_CODES = frozenset(
    {
        "CAPABILITY_UNAVAILABLE",
        "DENIED",
        "DUPLICATE_ACTIVE_RUN",
        "NOT_REGISTERED",
        "POLICY_REQUIREMENT_UNMET",
        "SCOPE_DENIED",
        "STALE_EPOCH",
    }
)
_RESOURCE_NOT_CONFIGURED_CODES = frozenset({"ACCOUNT_NOT_CONFIGURED", "SCOPE_NOT_CONFIGURED"})
_WORKER_FAILURE_CODES = frozenset(
    {
        "START_FAILED",
        "MAINTAIN_FAILED",
        "CLOSE_FAILED",
        "NOT_STARTED",
        "CLOSED",
        "QUEUE_FULL",
    }
)


def configure_service_read(
    directory: ServiceReadAccessDirectory | None,
) -> None:
    """Install or clear the trusted subject-to-worker directory.

    Worker lifecycle remains with the composition root. Bare synchronous
    clients are rejected so authenticated users cannot share one read session.
    """

    global _access_directory
    if directory is not None and type(directory) is not ServiceReadAccessDirectory:
        raise ServiceReadAccessError("INVALID_ACCESS_DIRECTORY")
    _access_directory = directory


def _require_directory() -> ServiceReadAccessDirectory:
    directory = _access_directory
    if directory is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "SERVICE_READ_NOT_CONFIGURED",
                "message": (
                    "This deployment has no authorized service read path; "
                    "no account or strategy facts are projected."
                ),
            },
        )
    return directory


def list_authorized_service_account_refs(subject: str) -> tuple[str, ...]:
    """Return the configured account refs granted to one authenticated subject."""

    directory = _access_directory
    return () if directory is None else directory.account_refs_for(subject)


async def read_authorized_service_account(
    subject: str, account_ref: str
) -> AccountReadView:
    """Read one account through the existing subject-bound service worker.

    This in-process bridge has the same exact subject/account authorization as
    the HTTP route and never creates a client or starts a worker.
    """

    directory = _access_directory
    if directory is None:
        raise ServiceReadUnavailableError("SERVICE_READ_NOT_CONFIGURED")
    try:
        access = directory.resolve_account(subject, account_ref)
    except ServiceReadAccessError:
        raise ServiceReadUnavailableError("ACCOUNT_READ_ACCESS_DENIED") from None
    try:
        return await access.worker.read_account(account_ref)
    except ServiceReadUnavailableError:
        raise


def _resolve_access(
    current_user: TokenPayload,
    selector: str,
    selector_kind: Literal[
        "account",
        "account_book",
        "account_member",
        "strategy_book",
        "order",
        "order_submit",
        "approved_target",
        "paper_submit",
        "paper_legacy_import",
        "monitor",
        "portfolio_analytics",
        "risk_policy_budget",
        "risk_account_policy",
    ],
) -> ReadAccess:
    directory = _require_directory()
    if type(current_user) is not TokenPayload:
        raise _access_denied() from None
    try:
        if selector_kind == "account":
            return directory.resolve_account(current_user.sub, selector)
        if selector_kind == "account_book":
            return directory.resolve_account_book(current_user.sub, selector)
        if selector_kind == "account_member":
            return directory.resolve_account_member(current_user.sub, selector)
        if selector_kind == "strategy_book":
            return directory.resolve_strategy_book(current_user.sub, selector)
        if selector_kind == "order":
            return directory.resolve_order_scope(current_user.sub, selector)
        if selector_kind == "order_submit":
            return directory.resolve_order_submit_scope(current_user.sub, selector)
        if selector_kind == "approved_target":
            return directory.resolve_approved_target_scope(current_user.sub, selector)
        if selector_kind == "paper_submit":
            return directory.resolve_paper_submit_account(current_user.sub, selector)
        if selector_kind == "paper_legacy_import":
            return directory.resolve_paper_legacy_import_account(current_user.sub, selector)
        if selector_kind == "monitor":
            return directory.resolve_monitor_scope(current_user.sub, selector)
        if selector_kind == "portfolio_analytics":
            return directory.resolve_portfolio_analytics(current_user.sub, selector)
        if selector_kind == "risk_policy_budget":
            return directory.resolve_risk_policy_budget(current_user.sub, selector)
        if selector_kind == "risk_account_policy":
            return directory.resolve_risk_account_policy(current_user.sub, selector)
    except ServiceReadAccessError:
        raise _access_denied() from None
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": "SERVICE_READ_FAILED",
            "message": "The authorized service could not answer.",
        },
    )


def resolve_portfolio_analytics_access(
    current_user: TokenPayload, portfolio_ref: str
) -> ReadAccess:
    """Resolve a deployment-owned offline analytics binding for this subject."""

    return _resolve_access(current_user, portfolio_ref, "portfolio_analytics")


def resolve_risk_policy_budget_access(
    current_user: TokenPayload, portfolio_ref: str
) -> ReadAccess:
    """Resolve one deployment-owned budget-control binding for this subject."""

    return _resolve_access(current_user, portfolio_ref, "risk_policy_budget")


def resolve_risk_account_policy_access(
    current_user: TokenPayload, account_ref: str
) -> ReadAccess:
    """Resolve one exact account-only policy grant for the authenticated subject."""

    return _resolve_access(current_user, account_ref, "risk_account_policy")


def resolve_paper_submit_access(
    subject: str, legacy_account_id: str
) -> tuple[ReadAccess, Any]:
    """Resolve a legacy account selector to its server-owned paper binding.

    Callers pass only the authenticated subject and public legacy account ID.
    Scope references and the paper domain remain deployment-owned.
    """

    directory = _require_directory()
    try:
        access = directory.resolve_paper_submit_account(subject, legacy_account_id)
    except ServiceReadAccessError:
        raise _access_denied() from None
    binding = access.paper_submit_bindings.get(legacy_account_id)
    if binding is None:
        raise _access_denied() from None
    return access, binding


def resolve_paper_legacy_import_access(
    current_user: TokenPayload, legacy_account_id: str
) -> tuple[ReadAccess, Any]:
    """Resolve one explicit import grant from the authenticated subject."""

    if type(current_user) is not TokenPayload:
        raise _access_denied() from None
    directory = _require_directory()
    try:
        access = directory.resolve_paper_legacy_import_account(
            current_user.sub, legacy_account_id
        )
    except ServiceReadAccessError:
        raise _access_denied() from None
    binding = access.paper_legacy_import_bindings.get(legacy_account_id)
    if binding is None or binding.owner_subject != current_user.sub:
        raise _access_denied() from None
    return access, binding


def _access_denied() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": "SERVICE_READ_ACCESS_DENIED",
            "message": "The requested service-read scope is not authorized.",
        },
    )


def _unavailable(code: str) -> HTTPException:
    if code in _FORBIDDEN_CODES or code in _RESOURCE_NOT_CONFIGURED_CODES:
        return _access_denied()
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"code": code, "message": "The authorized service could not answer."},
    )


def _worker_failure(error: BaseException, category: str) -> HTTPException:
    code = getattr(error, "code", None)
    if type(code) is str and code in _WORKER_FAILURE_CODES:
        public_code = code
    else:
        logger.warning("authorized %s read failed: %s", category, type(error).__name__)
        public_code = "SERVICE_READ_FAILED"
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"code": public_code, "message": "The authorized service could not answer."},
    )


def _decimal_text(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def _account_payload(view: AccountReadView) -> dict[str, Any]:
    return {
        "account_ref": view.account_ref,
        "execution_domain_ref": view.execution_domain_ref,
        "currency": view.currency,
        "quality": view.quality.value,
        "has_current_facts": view.has_current_facts,
        "cash": _decimal_text(view.cash),
        "value": _decimal_text(view.value),
        "observed_at_utc": view.observed_at_utc,
        "received_age_seconds": view.received_age_seconds,
        "fresh_for_seconds": view.fresh_for_seconds,
        "session_generation": view.session_generation,
        "cursor": view.cursor,
        "positions_count": view.positions_count,
        "open_orders_count": view.open_orders_count,
        "detail_code": view.detail_code,
        "authority": "provider account facts, not a strategy allocation or portfolio valuation",
    }


def _order_payload(view: OrderReadView) -> dict[str, Any]:
    return {
        "intent_id": view.intent_id,
        "quality": view.quality.value,
        "state": view.state,
        "provider_order_id": view.provider_order_id,
        "filled_quantity": _decimal_text(view.filled_quantity),
        "average_price": _decimal_text(view.average_price),
        "cumulative_commission": _decimal_text(view.cumulative_commission),
        "is_terminal": view.is_terminal,
        "is_unknown": view.is_unknown,
        "unknown_reason": view.unknown_reason,
        "review_required": view.review_required,
        "updated_at_ns": view.updated_at_ns,
        "detail_code": view.detail_code,
        "authority": "durable execution journal record, not a strategy ledger",
    }


def _health_payload(view: StrategyHealthView) -> dict[str, Any]:
    return {
        "strategy_ref": view.strategy_ref,
        "scope_ref": view.scope_ref,
        "quality": view.quality.value,
        "is_healthy": view.is_healthy,
        "stream_id": view.stream_id,
        "sequence": view.sequence,
        "heartbeat_age_seconds": view.heartbeat_age_seconds,
        "metrics_age_seconds": view.metrics_age_seconds,
        "metrics": dict(view.metrics),
        "detail_code": view.detail_code,
        "authority": "producer heartbeat observation, not trading readiness",
    }


@router.get("/service-read/consumers")
async def list_service_read_consumers(
    current_user: TokenPayload = Depends(get_current_user),
) -> dict[str, Any]:
    """List the registered service consumers and their recorded evidence."""

    del current_user
    consumers = validate_consumers()
    return {
        "consumers": [
            {
                "consumer_id": consumer.consumer_id,
                "surface": consumer.surface,
                "capability": consumer.capability,
                "status": consumer.status,
                "evidence": consumer.evidence,
                "authority_owner": consumer.authority_owner,
                "notes": consumer.notes,
            }
            for consumer in consumers
        ],
        "migrated": sorted(
            consumer_id
            for consumer_id, consumer in CONSUMERS.items()
            if consumer.status != "pending"
        ),
    }


@router.get("/service-read/accounts/{account_ref}")
async def read_service_account(
    account_ref: str,
    currency: str | None = None,
    current_user: TokenPayload = Depends(get_current_user),
) -> dict[str, Any]:
    """Return the authorized account view for one configured account."""

    access = _resolve_access(current_user, account_ref, "account")
    try:
        view = await access.worker.read_account(account_ref, currency=currency)
    except ServiceReadUnavailableError as error:
        raise _unavailable(error.code) from None
    except Exception as error:  # noqa: BLE001 - finite local diagnostics only
        raise _worker_failure(error, "account") from None
    return _account_payload(view)


@router.get("/service-read/orders/{intent_id}")
async def read_service_order(
    intent_id: str,
    scope_ref: str,
    current_user: TokenPayload = Depends(get_current_user),
) -> dict[str, Any]:
    """Return the authorized durable record for one managed order.

    The scope reference is explicit: an order is only readable through the
    order-query scope this deployment granted, never through an inferred one.
    """

    access = _resolve_access(current_user, scope_ref, "order")
    try:
        view = await access.worker.read_order(scope_ref, intent_id)
    except ServiceReadUnavailableError as error:
        raise _unavailable(error.code) from None
    except Exception as error:  # noqa: BLE001 - finite local diagnostics only
        raise _worker_failure(error, "order") from None
    return _order_payload(view)


@router.get("/service-read/strategy-health/{scope_ref}")
async def read_service_strategy_health(
    scope_ref: str,
    current_user: TokenPayload = Depends(get_current_user),
) -> dict[str, Any]:
    """Return the authorized heartbeat view for one telemetry scope."""

    access = _resolve_access(current_user, scope_ref, "monitor")
    try:
        view = await access.worker.read_strategy_health(scope_ref)
    except ServiceReadUnavailableError as error:
        raise _unavailable(error.code) from None
    except Exception as error:  # noqa: BLE001 - finite local diagnostics only
        raise _worker_failure(error, "strategy") from None
    return _health_payload(view)
