import asyncio

import pytest


@pytest.mark.asyncio
async def test_ws_gateway_auth_subscribe_and_publish_fanout():
    from app.services.ws_gateway import WSGateway

    gateway = WSGateway(token_validator=lambda token: token == "valid")

    assert await gateway.connect("client-bad", token="bad") is False
    assert await gateway.connect("client-a", token="valid") is True
    assert await gateway.connect("client-b", token="valid") is True

    await gateway.subscribe("client-a", ["market:quote:*"])
    await gateway.subscribe("client-b", ["market:quote:RB2510"])
    delivered = await gateway.publish("market:quote:RB2510", {"price": 100})

    assert delivered == 2
    assert gateway.metrics().connection_count == 2
    assert gateway.metrics().subscription_count == 2


@pytest.mark.asyncio
async def test_ws_gateway_heartbeat_timeout_disconnects_idle_client():
    from app.services.ws_gateway import WSGateway

    gateway = WSGateway(token_validator=lambda token: True, heartbeat_timeout_ms=5)
    await gateway.connect("client-a", token="any")
    await asyncio.sleep(0.01)

    closed = gateway.close_idle_connections()

    assert closed == ["client-a"]
    assert gateway.metrics().connection_count == 0


@pytest.mark.asyncio
async def test_ws_gateway_bounds_messages_and_purges_idle_client_queue():
    from app.services.ws_gateway import WSGateway

    gateway = WSGateway(
        token_validator=lambda token: True,
        heartbeat_timeout_ms=5,
        max_messages=3,
    )
    await gateway.connect("idle-client", token="any")
    await gateway.connect("active-client", token="any")
    await gateway.subscribe("idle-client", ["market:*"])
    await gateway.subscribe("active-client", ["market:*"])

    await asyncio.sleep(0.01)
    gateway.touch("active-client")
    await gateway.publish("market:a", {"idx": 1})
    await gateway.publish("market:b", {"idx": 2})

    # Queue is capped at max_messages=3 (oldest message discarded)
    assert len(gateway._messages) == 3

    # Mark idle-client stale without touching active-client
    gateway._connections["idle-client"] = 0.0
    closed = gateway.close_idle_connections()

    assert closed == ["idle-client"]
    assert all(client_id != "idle-client" for client_id, _, _ in gateway._messages)
    assert any(client_id == "active-client" for client_id, _, _ in gateway._messages)
