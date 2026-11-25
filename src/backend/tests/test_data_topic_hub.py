import asyncio

import pytest


@pytest.mark.asyncio
async def test_data_topic_hub_ttl_coalesce_push_only_drop_and_retire():
    from app.services.data_topic_hub import DataTopicHub, Producer, TopicPolicy

    calls: list[list[str]] = []

    class QuoteProducer(Producer):
        def topic_patterns(self) -> list[str]:
            return ["market:quote:*"]

        async def refresh(self, topics: list[str]) -> dict[str, dict]:
            calls.append(topics)
            return {
                topic: {"symbol": topic.rsplit(":", 1)[-1], "price": 100 + len(calls)}
                for topic in topics
            }

        def max_requests_per_sec(self) -> float:
            return 100.0

    hub = DataTopicHub()
    hub.register_topic(
        "market:quote:RB2510",
        TopicPolicy(ttl_ms=200, coalesce_within_ms=50, drop_on_idle=True),
    )
    hub.register_topic("market:quote:PUSH", TopicPolicy(push_only=True, ttl_ms=200))
    hub.register_producer(QuoteProducer())

    first = await hub.peek("market:quote:RB2510")
    second = await hub.peek("market:quote:RB2510")
    assert first["price"] == second["price"]
    assert len(calls) == 1

    assert await hub.peek("market:quote:PUSH") is None

    received: list[dict] = []
    subscription_id = hub.subscribe(
        "tester", "market:quote:*", lambda topic, value: received.append(value)
    )
    await hub.push("market:quote:RB2510", {"price": 101})
    await hub.push("market:quote:RB2510", {"price": 102})
    await asyncio.sleep(0.06)
    assert received[-1] == {"price": 102}

    hub.unsubscribe(subscription_id)
    hub.retire_topic("market:quote:RB2510")
    assert hub.peek_raw("market:quote:RB2510") is None


@pytest.mark.asyncio
async def test_data_topic_hub_refresh_timeout_and_error_subscriber():
    from app.services.data_topic_hub import DataTopicHub, Producer, TopicPolicy

    class SlowProducer(Producer):
        def topic_patterns(self) -> list[str]:
            return ["market:history:*"]

        async def refresh(self, topics: list[str]) -> dict[str, dict]:
            await asyncio.sleep(0.05)
            return {topic: {"ok": True} for topic in topics}

    errors: list[dict] = []
    hub = DataTopicHub()
    hub.register_topic("market:history:RB2510:D1:1d", TopicPolicy(refresh_timeout_ms=10))
    hub.register_producer(SlowProducer())
    hub.subscribe_errors(lambda error: errors.append(error))

    value = await hub.request("market:history:RB2510:D1:1d", force=True)

    assert value is None
    assert errors[-1]["topic"] == "market:history:RB2510:D1:1d"
    assert errors[-1]["code"] == "refresh_timeout"


@pytest.mark.asyncio
async def test_data_topic_hub_push_forwards_to_ws_gateway():
    from app.services.data_topic_hub import DataTopicHub, TopicPolicy
    from app.services.ws_gateway import WSGateway

    hub = DataTopicHub()
    gateway = WSGateway(token_validator=lambda token: True)
    await gateway.connect("client-a", token="ok")
    await gateway.subscribe("client-a", ["market:quote:*"])
    hub.set_ws_gateway(gateway)
    hub.register_topic("market:quote:RB2510", TopicPolicy(ttl_ms=200))

    delivered = await hub.push("market:quote:RB2510", {"price": 101})

    assert delivered == 1
    assert gateway._messages == [("client-a", "market:quote:RB2510", {"price": 101})]


@pytest.mark.asyncio
async def test_data_topic_hub_lru_eviction_and_tracked_task_cleanup(caplog, tmp_path, monkeypatch):
    import sqlite3

    from app.services.auto_trading_scheduler import AutoTradingScheduler
    from app.services.data_topic_hub import DataTopicHub
    from app.services.monitoring_control import (
        OwnerControlDeployment,
        OwnerControlError,
    )
    from app.services.sync.progress import prune_sync_tasks
    from app.utils.async_tasks import get_tracked_tasks, spawn_tracked_task

    # 1. DataTopicHub caps topics via LRU and cleans up retired state
    hub = DataTopicHub(max_topics=2)
    await hub.push("topic:1", {"v": 1})
    await hub.push("topic:2", {"v": 2})
    await hub.push("topic:1", {"v": 11})  # Touch topic:1 so topic:2 becomes LRU
    await hub.push("topic:3", {"v": 3})
    assert hub.peek_raw("topic:2") is None
    assert hub.peek_raw("topic:1") == {"v": 11}
    assert hub.peek_raw("topic:3") == {"v": 3}

    # 2. spawn_tracked_task holds strong refs, cleans up on finish, and logs exceptions
    async def _boom() -> None:
        raise RuntimeError("background boom")

    with caplog.at_level("ERROR"):
        task = spawn_tracked_task(_boom(), name="ocr35-boom")
        assert task in get_tracked_tasks()
        await asyncio.sleep(0.02)
    assert task not in get_tracked_tasks()
    assert "ocr35-boom" in caplog.text

    # 3. prune_sync_tasks evicts completed tasks before active ones
    tasks = {
        "done-1": {"status": "completed"},
        "run-1": {"status": "running"},
        "done-2": {"status": "failed"},
        "run-2": {"status": "running"},
    }
    prune_sync_tasks(tasks, max_entries=2)
    assert set(tasks.keys()) == {"run-1", "run-2"}

    # 4. AutoTradingScheduler.shutdown stops background loop cleanly
    scheduler = AutoTradingScheduler()
    scheduler._running = True
    scheduler._task = asyncio.create_task(asyncio.sleep(10))
    await scheduler.shutdown()
    assert scheduler._running is False
    assert scheduler._task is None

    # 5. monitoring_control closes SQLite connection when DDL initialization fails
    closed_connections: list[bool] = []
    real_connect = sqlite3.connect

    class _TrackedConn:
        def __init__(self, inner: sqlite3.Connection) -> None:
            self._inner = inner
            self.row_factory = None

        def execute(self, sql: str, *args, **kwargs):
            if "CREATE TABLE" in sql:
                raise sqlite3.OperationalError("forced ddl error")
            return self._inner.execute(sql, *args, **kwargs)

        def close(self) -> None:
            closed_connections.append(True)
            self._inner.close()

    monkeypatch.setattr(
        "app.services.monitoring_control.sqlite3.connect",
        lambda path, timeout=5.0: _TrackedConn(real_connect(":memory:")),
    )
    svc = OwnerControlDeployment.__new__(OwnerControlDeployment)
    svc._state_path = tmp_path / "state.sqlite3"
    with pytest.raises(OwnerControlError, match="ISSUER_STATE_UNAVAILABLE"):
        svc._connect_issuer_state()
    assert closed_connections == [True]
