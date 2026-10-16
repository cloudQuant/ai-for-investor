"""Authenticated WebSocket projection of authorized Gateway health facts."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.afi_owner_scope import require_persisted_owner_scope
from app.api._dependencies import get_websocket_current_user
from app.api.service_gateway import _gateway_health_payload
from app.api.service_read import _resolve_access
from app.db.database import get_db
from app.schemas.auth import TokenPayload
from app.services.service_read.client import ServiceReadUnavailableError

router = APIRouter()

_HEALTH_PUSH_INTERVAL_SECONDS = 5.0


@router.websocket("/service-gateway/ws/accounts/{account_ref}/health")
async def stream_service_gateway_health(
    websocket: WebSocket,
    account_ref: str,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Stream only the same HTTP health projection for an authenticated owner.

    The socket carries no provider commands or credential material. It may
    send ``refresh`` or ``close``; every refresh re-resolves the account
    against the current deployment directory before reading the Gateway
    owner-backed status.
    """

    current_user, accepted_subprotocol = get_websocket_current_user(websocket)
    if (
        type(current_user) is not TokenPayload
        or accepted_subprotocol != "access-token"
    ):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    try:
        # Start the persisted-owner check in a fresh read transaction. A long
        # lived WebSocket may otherwise keep a repeatable-read snapshot or a
        # cached ORM identity from the initial handshake.
        await db.rollback()
        persisted_owner = await require_persisted_owner_scope(current_user, db)
        if persisted_owner.owner_subject != current_user.sub:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        # Resolve once before accepting so a disallowed account never opens a
        # socket. It is re-resolved before each projection below.
        _resolve_access(current_user, account_ref, "account")
    except HTTPException:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept(subprotocol=accepted_subprotocol)
    try:
        while True:
            try:
                # Re-decode the immutable original handshake token before
                # every projection. Identity can only come from that token;
                # WebSocket messages are never accepted as identity input.
                refreshed_user, refreshed_protocol = get_websocket_current_user(websocket)
                if (
                    type(refreshed_user) is not TokenPayload
                    or refreshed_protocol != accepted_subprotocol
                    or refreshed_user.sub != current_user.sub
                ):
                    await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                    return

                # End the previous read transaction before checking revocation
                # so AsyncSession.get cannot satisfy the check from an old
                # identity-map entry or repeatable-read snapshot.
                await db.rollback()
                persisted_owner = await require_persisted_owner_scope(refreshed_user, db)
                if persisted_owner.owner_subject != current_user.sub:
                    await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                    return
                access = _resolve_access(refreshed_user, account_ref, "account")
                view = await access.worker.read_gateway_health(account_ref)
                await websocket.send_json(
                    {"type": "gateway_health", "data": _gateway_health_payload(view)}
                )
            except HTTPException:
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                return
            except ServiceReadUnavailableError:
                await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
                return
            except Exception:  # noqa: BLE001 - never reflect provider diagnostics.
                await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
                return

            try:
                message = await asyncio.wait_for(
                    websocket.receive_text(), timeout=_HEALTH_PUSH_INTERVAL_SECONDS
                )
            except TimeoutError:
                continue
            except WebSocketDisconnect:
                return

            if message == "close":
                await websocket.close(code=status.WS_1000_NORMAL_CLOSURE)
                return
            if message != "refresh":
                await websocket.close(code=status.WS_1003_UNSUPPORTED_DATA)
                return
    except WebSocketDisconnect:
        return
