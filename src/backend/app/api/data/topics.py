import asyncio
import logging
import math
import time
import typing
from collections import defaultdict, deque
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status

from app.api.data.deps import require_data_admin_user
from app.api.deps import get_current_user, get_websocket_current_user
from app.services.data_topic_hub import TopicPolicy, get_shared_data_topic_hub
from app.services.ws_gateway import get_shared_ws_gateway

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/data-topics", tags=["Data Topics"])
_PUBLIC_TOPIC_PREFIXES = ("market:",)
_USER_TOPIC_WRITE_LIMIT = 12
_USER_TOPIC_WRITE_WINDOW_SECONDS = 60.0
_user_topic_writes: dict[str, deque[float]] = defaultdict(deque)


def _owns_user_topic(topic: str, user_id: str) -> bool:
    return topic.startswith(f"user:{user_id}:")


def _can_read_topic(topic: str, user_id: str) -> bool:
    return topic.startswith(_PUBLIC_TOPIC_PREFIXES) or _owns_user_topic(topic, user_id)


def _require_topic_access(topic: str, user_id: str, *, write: bool = False) -> None:
    """Enforce namespace ACLs for externally accessible data topics."""
    allowed = _owns_user_topic(topic, user_id) if write else _can_read_topic(topic, user_id)
    if not allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Topic access denied")


def _require_topic_pattern_access(pattern: str, user_id: str) -> None:
    """Only permit public-market or caller-owned namespace subscriptions."""
    if pattern.startswith(_PUBLIC_TOPIC_PREFIXES) or _owns_user_topic(pattern, user_id):
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Topic subscription denied")


def _consume_user_topic_write(user_id: str) -> None:
    now = time.monotonic()
    window_start = now - _USER_TOPIC_WRITE_WINDOW_SECONDS
    writes = _user_topic_writes[user_id]
    while writes and writes[0] <= window_start:
        writes.popleft()
    if len(writes) >= _USER_TOPIC_WRITE_LIMIT:
        retry_after = max(1, math.ceil(writes[0] + _USER_TOPIC_WRITE_WINDOW_SECONDS - now))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="User topic write quota exceeded",
            headers={"Retry-After": str(retry_after)},
        )
    writes.append(now)


def _authorize_user_topic_write(topic: str, user_id: str, action: str) -> None:
    _require_topic_access(topic, user_id, write=True)
    _consume_user_topic_write(user_id)
    logger.info("data_topic_write actor=%s action=%s topic=%s", user_id, action, topic)


@router.get("", response_model=None)
async def list_topics(current_user: typing.Any = Depends(get_current_user)) -> typing.Any:
    items = [
        item
        for item in get_shared_data_topic_hub().list_topics()
        if _can_read_topic(str(item["topic"]), current_user.sub)
    ]
    return {"items": items, "total": len(items)}


@router.post("/register", response_model=None)
async def register_topic(
    payload: dict, current_user: typing.Any = Depends(require_data_admin_user)
) -> typing.Any:
    topic = str(payload["topic"])
    policy = TopicPolicy(**dict(payload.get("policy") or {}))
    get_shared_data_topic_hub().register_topic(topic, policy)
    return {"topic": topic, "policy": asdict(policy)}


@router.get("/stats", response_model=None)
async def topic_stats(current_user: typing.Any = Depends(require_data_admin_user)) -> typing.Any:
    return get_shared_data_topic_hub().stats()


@router.get("/{topic:path}/peek", response_model=None)
async def peek_topic(
    topic: str, current_user: typing.Any = Depends(get_current_user)
) -> typing.Any:
    _require_topic_access(topic, current_user.sub)
    value = await get_shared_data_topic_hub().peek(topic)
    return {"topic": topic, "value": value}


@router.post("/{topic:path}/refresh", response_model=None)
async def refresh_topic(
    topic: str, current_user: typing.Any = Depends(get_current_user)
) -> typing.Any:
    _authorize_user_topic_write(topic, current_user.sub, "refresh")
    value = await get_shared_data_topic_hub().request(topic, force=True)
    return {"topic": topic, "value": value}


@router.post("/{topic:path}/push", response_model=None)
async def push_topic(
    topic: str, payload: dict, current_user: typing.Any = Depends(get_current_user)
) -> typing.Any:
    _authorize_user_topic_write(topic, current_user.sub, "push")
    delivered = await get_shared_data_topic_hub().push(topic, payload.get("value"))
    return {"topic": topic, "delivered": delivered}


def _bind_shared_topic_gateway() -> typing.Any:
    hub = get_shared_data_topic_hub()
    gateway = get_shared_ws_gateway()
    hub.set_ws_gateway(gateway)
    return hub, gateway


async def _stream_topics_websocket(
    websocket: WebSocket, *, topic: str | None = None, pattern: str | None = None
) -> None:
    current_user, accepted_subprotocol = await get_websocket_current_user(websocket)
    if current_user is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    try:
        if topic is not None:
            _require_topic_access(topic, current_user.sub)
        else:
            _require_topic_pattern_access(pattern or "", current_user.sub)
    except HTTPException:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    hub, gateway = _bind_shared_topic_gateway()
    client_id = f"data-topic-{id(websocket)}"
    subscribed_pattern = pattern or topic or "*"
    connected = await gateway.connect(client_id, token=current_user.sub)
    if not connected:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept(subprotocol=accepted_subprotocol)
    await gateway.subscribe(client_id, [subscribed_pattern])
    await websocket.send_json({"type": "connected", "topic": topic, "pattern": pattern})

    if topic is not None:
        initial_value = await hub.peek(topic)
        if initial_value is not None:
            await websocket.send_json({"type": "snapshot", "topic": topic, "value": initial_value})

    try:
        while True:
            pending = gateway.pop_messages(client_id)
            for matched_topic, payload in pending:
                await websocket.send_json(
                    {"type": "topic_update", "topic": matched_topic, "value": payload}
                )

            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=0.1)
            except asyncio.TimeoutError:
                continue

            if data == "ping":
                await websocket.send_json({"type": "pong"})
                continue

            if data == "refresh" and topic is not None:
                try:
                    _authorize_user_topic_write(topic, current_user.sub, "websocket_refresh")
                except HTTPException:
                    await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                    return
                value = await hub.request(topic, force=True)
                await websocket.send_json({"type": "snapshot", "topic": topic, "value": value})
    except WebSocketDisconnect:
        pass
    finally:
        gateway.disconnect(client_id)


async def websocket_topic_endpoint(websocket: WebSocket, topic: str) -> None:
    await _stream_topics_websocket(websocket, topic=topic)


async def websocket_pattern_endpoint(websocket: WebSocket) -> None:
    pattern = websocket.query_params.get("pattern") or "*"
    await _stream_topics_websocket(websocket, pattern=pattern)
