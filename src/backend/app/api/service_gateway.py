"""Authorized Gateway status projections over the SDK service-read owner."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.api.service_read import _resolve_access, _unavailable, _worker_failure
from app.schemas.auth import TokenPayload
from app.services.service_read.client import ServiceReadUnavailableError
from app.services.service_read.contracts import AccountReadView, ReadQuality
from app.services.service_read.gateway_health import GatewayHealthView

router = APIRouter()


def _gateway_health_payload(view: GatewayHealthView) -> dict[str, Any]:
    observation: AccountReadView = view.account_observation
    if observation.quality in {ReadQuality.FRESH, ReadQuality.STALE}:
        observation_status = "observed"
    elif observation.quality is ReadQuality.UNAVAILABLE:
        observation_status = "unavailable"
    else:
        observation_status = "unobserved"

    generation_match: bool | None = None
    if view.session_generation is not None and observation.session_generation is not None:
        generation_match = view.session_generation == observation.session_generation

    return {
        "account_ref": view.account_ref,
        "service_connection": {"rpc_status": "reachable" if view.rpc_reachable else "unobserved"},
        "gateway_session": {
            "status": view.gateway_session_status,
            "session_generation": view.session_generation,
            "fresh_for_seconds": view.session_fresh_for_seconds,
        },
        "account_observation": {
            "status": observation_status,
            "quality": observation.quality.value,
            "observed_at_utc": observation.observed_at_utc,
            "received_age_seconds": observation.received_age_seconds,
            "fresh_for_seconds": observation.fresh_for_seconds,
            "session_generation": observation.session_generation,
            "cursor": observation.cursor,
            "same_session_generation": generation_match,
        },
        # Account snapshots do not establish that a market-data feed is active.
        "market_data_feed": {"status": "unobserved"},
        "authority": "authorized SDK Gateway owner status and account observation",
    }


@router.get("/service-gateway/accounts/{account_ref}/health")
async def read_service_gateway_health(
    account_ref: str,
    current_user: TokenPayload = Depends(get_current_user),
) -> dict[str, Any]:
    """Return separate connection, owner-session, account, and feed facts."""

    access = _resolve_access(current_user, account_ref, "account")
    try:
        view = await access.worker.read_gateway_health(account_ref)
    except ServiceReadUnavailableError as error:
        raise _unavailable(error.code) from None
    except Exception as error:  # noqa: BLE001 - finite diagnostics only
        raise _worker_failure(error, "Gateway health") from None
    return _gateway_health_payload(view)
