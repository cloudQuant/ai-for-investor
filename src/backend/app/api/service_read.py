"""Read-only application endpoints backed by the shared service packages.

The endpoints report what the authorized read path can prove and nothing more:
a value is returned only with its quality marker, an unreadable service answers
with an explicit unavailable status instead of a placeholder balance, and a
refused scope is a refusal rather than a degraded page.  Nothing here connects
to a provider, so opening the page never logs an account in.

The composition root installs the borrowed client with
:func:`configure_service_read`.  Without it the endpoints report
``not_configured``; they never construct a runtime on their own.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user
from app.services.service_read.client import (
    AuthorizedServiceReadClient,
    ServiceReadUnavailableError,
)
from app.services.service_read.consumers import CONSUMERS, validate_consumers
from app.services.service_read.contracts import (
    AccountReadView,
    OrderReadView,
    StrategyHealthView,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_client: AuthorizedServiceReadClient | None = None

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


def configure_service_read(client: AuthorizedServiceReadClient | None) -> None:
    """Install or clear the borrowed read client owned by the composition root."""

    global _client
    _client = client


def get_service_read_client() -> AuthorizedServiceReadClient | None:
    """Return the installed read client, if this deployment configured one."""

    return _client


def _require_client() -> AuthorizedServiceReadClient:
    client = get_service_read_client()
    if client is None:
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
    return client


def _unavailable(code: str) -> HTTPException:
    if code in _FORBIDDEN_CODES:
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": code, "message": "The requested scope is not authorized."},
        )
    if code.endswith("NOT_CONFIGURED"):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": code, "message": "The requested subject is not registered here."},
        )
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"code": code, "message": "The authorized service could not answer."},
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
    current_user: Any = Depends(get_current_user),
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
    current_user: Any = Depends(get_current_user),
) -> dict[str, Any]:
    """Return the authorized account view for one configured account."""

    del current_user
    client = _require_client()
    try:
        view = client.read_account(account_ref, currency=currency)
    except ServiceReadUnavailableError as error:
        raise _unavailable(error.code) from None
    except Exception as error:  # noqa: BLE001 - finite local diagnostics only
        logger.warning("authorized account read failed: %s", type(error).__name__)
        raise _unavailable("SERVICE_READ_FAILED") from None
    return _account_payload(view)


@router.get("/service-read/orders/{intent_id}")
async def read_service_order(
    intent_id: str,
    scope_ref: str,
    current_user: Any = Depends(get_current_user),
) -> dict[str, Any]:
    """Return the authorized durable record for one managed order.

    The scope reference is explicit: an order is only readable through the
    order-query scope this deployment granted, never through an inferred one.
    """

    del current_user
    client = _require_client()
    try:
        view = client.read_order(scope_ref, intent_id)
    except ServiceReadUnavailableError as error:
        raise _unavailable(error.code) from None
    except Exception as error:  # noqa: BLE001 - finite local diagnostics only
        logger.warning("authorized order read failed: %s", type(error).__name__)
        raise _unavailable("SERVICE_READ_FAILED") from None
    return _order_payload(view)


@router.get("/service-read/strategy-health/{scope_ref}")
async def read_service_strategy_health(
    scope_ref: str,
    current_user: Any = Depends(get_current_user),
) -> dict[str, Any]:
    """Return the authorized heartbeat view for one telemetry scope."""

    del current_user
    client = _require_client()
    try:
        view = client.read_strategy_health(scope_ref)
    except ServiceReadUnavailableError as error:
        raise _unavailable(error.code) from None
    except Exception as error:  # noqa: BLE001 - finite local diagnostics only
        logger.warning("authorized strategy read failed: %s", type(error).__name__)
        raise _unavailable("SERVICE_READ_FAILED") from None
    return _health_payload(view)
