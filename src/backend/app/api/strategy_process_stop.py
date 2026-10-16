"""Exact, owner-authorized stop for one service-managed strategy process."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, status

from app.api.afi_owner_scope import (
    PersistedOwnerScope,
    require_persisted_owner_scope,
)
from app.api.monitoring import get_owner_control_deployment
from app.services.live_trading.manager import get_existing_live_trading_manager
from app.services.live_trading.strategy_process_stop import (
    StrategyProcessStopError,
    select_stop_new_binding,
    stop_service_strategy_process,
)

router = APIRouter()


def get_service_strategy_manager() -> Any:
    """Return the existing manager without triggering legacy restoration."""

    manager = get_existing_live_trading_manager()
    if manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "STRATEGY_MANAGER_UNAVAILABLE"},
        )
    return manager


@router.post(
    "/service-strategy-processes/{instance_id}/stop",
    summary="Fence new strategy writes and gracefully stop one service run",
)
async def stop_service_strategy_process_route(
    instance_id: str,
    idempotency_key: str = Header(
        ...,
        alias="Idempotency-Key",
        min_length=1,
        max_length=256,
    ),
    owner: PersistedOwnerScope = Depends(require_persisted_owner_scope),
    manager: Any = Depends(get_service_strategy_manager),
    deployment: Any = Depends(get_owner_control_deployment),
) -> dict[str, Any]:
    """Stop only the authenticated owner's current exact service strategy run.

    The route takes an instance ID and a replay key only.  Strategy, run,
    account, profile, owner binding, and order policy all come from trusted
    server state.  A completed receipt means the process and its local SDK
    runtime closed; it does not claim orders were cancelled or positions
    were flattened.
    """

    try:
        binding = select_stop_new_binding(
            manager,
            deployment,
            subject=owner.owner_subject,
            instance_id=instance_id,
        )
        receipt = await stop_service_strategy_process(
            manager,
            deployment,
            subject=owner.owner_subject,
            instance_id=instance_id,
            binding=binding,
            idempotency_key=idempotency_key,
            open_order_policy="leave_open_and_report",
        )
    except StrategyProcessStopError as exc:
        _raise_stop_error(exc)

    if receipt.status == "stopped":
        return receipt.to_public_dict()
    if receipt.status == "partial":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=receipt.to_public_dict(),
        )
    # Unknown is intentionally nonterminal: keep the child and subscriptions
    # available for reconciliation and never claim that cancellation occurred.
    raise HTTPException(
        status_code=status.HTTP_202_ACCEPTED,
        detail=receipt.to_public_dict(),
    )


def _raise_stop_error(error: StrategyProcessStopError) -> None:
    codes = {
        "INSTANCE_NOT_FOUND": status.HTTP_404_NOT_FOUND,
        "OWNER_CONTROL_NOT_AUTHORIZED": status.HTTP_403_FORBIDDEN,
        "STOP_REQUEST_INVALID": 422,
        "SERVICE_STRATEGY_RUN_UNAVAILABLE": status.HTTP_409_CONFLICT,
        "OWNER_CONTROL_BINDING_AMBIGUOUS": status.HTTP_503_SERVICE_UNAVAILABLE,
        "OWNER_CONTROL_BINDING_INVALID": status.HTTP_503_SERVICE_UNAVAILABLE,
        "SERVICE_STRATEGY_SCOPE_MISMATCH": status.HTTP_503_SERVICE_UNAVAILABLE,
        "OWNER_CONTROL_RUN_MISMATCH": status.HTTP_503_SERVICE_UNAVAILABLE,
        "ORDER_POLICY_UNSUPPORTED": 422,
    }
    raise HTTPException(
        status_code=codes.get(error.code, status.HTTP_503_SERVICE_UNAVAILABLE),
        detail={"code": error.code},
    ) from None
