"""Owner-thread behavior tests without importing the application package."""

from __future__ import annotations

import asyncio
import importlib.util
import threading
import time
from functools import wraps
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_WORKER_PATH = Path(__file__).resolve().parents[1] / "app/services/service_read/worker.py"
_SPEC = importlib.util.spec_from_file_location("_service_read_worker_test_subject", _WORKER_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_WORKER_MODULE: ModuleType = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_WORKER_MODULE)
ServiceReadWorker = _WORKER_MODULE.ServiceReadWorker
ServiceReadWorkerError = _WORKER_MODULE.ServiceReadWorkerError


def _run_async(test: Any) -> Any:
    """Keep pytest nodes synchronous when the asyncio plugin is disabled."""

    @wraps(test)
    def run(*args: Any, **kwargs: Any) -> None:
        asyncio.run(test(*args, **kwargs))

    return run


class _Session:
    def __init__(
        self,
        *,
        start_error: bool = False,
        maintain_error: bool = False,
        close_error: bool = False,
        read_error: type[BaseException] | None = None,
        block_start: bool = False,
        block_read: bool = False,
    ) -> None:
        self.start_error = start_error
        self.maintain_error = maintain_error
        self.close_error = close_error
        self.read_error = read_error
        self.start_entered = threading.Event()
        self.release_start = threading.Event()
        if not block_start:
            self.release_start.set()
        self.read_entered = threading.Event()
        self.release_read = threading.Event()
        if not block_read:
            self.release_read.set()
        self.calls: list[tuple[str, int, tuple[Any, ...]]] = []

    def _record(self, name: str, *arguments: Any) -> None:
        self.calls.append((name, threading.get_ident(), arguments))

    def start(self) -> None:
        self._record("start")
        self.start_entered.set()
        self.release_start.wait()
        if self.start_error:
            raise RuntimeError("private session detail")

    def maintain(self) -> None:
        self._record("maintain")
        if self.maintain_error:
            raise RuntimeError("private maintenance detail")

    def _read(self, name: str, *arguments: Any) -> tuple[str, tuple[Any, ...]]:
        self._record(name, *arguments)
        self.read_entered.set()
        self.release_read.wait()
        if self.read_error is not None:
            error_type = self.read_error
            self.read_error = None
            raise error_type("private read detail")
        return name, arguments

    def read_account(self, account_ref: str, *, currency: str | None = None) -> Any:
        return self._read("read_account", account_ref, currency)

    def read_order(self, scope_ref: str, intent_id: str) -> Any:
        return self._read("read_order", scope_ref, intent_id)

    def read_strategy_health(self, scope_ref: str) -> Any:
        return self._read("read_strategy_health", scope_ref)

    def close(self) -> None:
        self._record("close")
        if self.close_error:
            raise RuntimeError("private close detail")


def _worker(
    holder: dict[str, Any],
    *,
    max_queue_size: int = 4,
    maintenance_interval_seconds: float = 10.0,
    **session_options: Any,
) -> Any:
    def factory() -> _Session:
        holder["factory_thread_id"] = threading.get_ident()
        session = _Session(**session_options)
        holder["session"] = session
        holder["factory_created"].set()
        return session

    holder["factory_created"] = threading.Event()
    return ServiceReadWorker(
        factory,
        max_queue_size=max_queue_size,
        maintenance_interval_seconds=maintenance_interval_seconds,
        name="test-service-read-owner",
    )


async def _wait_thread_event(event: threading.Event) -> None:
    deadline = time.monotonic() + 2.0
    while not event.is_set():
        if time.monotonic() >= deadline:
            raise AssertionError("worker thread did not reach the expected point")
        await asyncio.sleep(0.001)


async def _cleanup_worker(
    worker: Any,
    holder: dict[str, Any],
    *,
    tasks: tuple[asyncio.Task[Any] | None, ...] = (),
    close_task: asyncio.Task[Any] | None = None,
) -> None:
    session = holder.get("session")
    if session is not None:
        session.release_start.set()
        session.release_read.set()
    for task in tasks:
        if task is not None and not task.done():
            task.cancel()
    await asyncio.gather(*(task for task in tasks if task is not None), return_exceptions=True)
    try:
        await worker.aclose()
    except ServiceReadWorkerError:
        # Failure-path tests may already have asserted a lifecycle error.
        pass
    if close_task is not None:
        await asyncio.gather(close_task, return_exceptions=True)


@_run_async
async def test_all_session_lifecycle_and_reads_stay_on_factory_thread() -> None:
    holder: dict[str, Any] = {}
    worker = _worker(holder, maintenance_interval_seconds=0.01)
    caller_thread = threading.get_ident()

    try:
        await worker.start()
        assert await worker.read_account("account-a", currency="USD") == (
            "read_account",
            ("account-a", "USD"),
        )
        assert await worker.read_order("orders-a", "intent-1") == (
            "read_order",
            ("orders-a", "intent-1"),
        )
        assert await worker.read_strategy_health("health-a") == (
            "read_strategy_health",
            ("health-a",),
        )
        await _wait_thread_event(holder["session"].read_entered)
        await asyncio.sleep(0.03)
        await worker.aclose()

        session = holder["session"]
        thread_ids = {thread_id for _, thread_id, _ in session.calls}
        assert len(thread_ids) == 1
        assert caller_thread not in thread_ids
        assert holder["factory_thread_id"] in thread_ids
        assert [name for name, _, _ in session.calls][0] == "start"
        assert "maintain" in [name for name, _, _ in session.calls]
        assert [name for name, _, _ in session.calls][-1] == "close"
        assert worker._thread is not None and not worker._thread.is_alive()
    finally:
        await _cleanup_worker(worker, holder)


@_run_async
async def test_maintenance_runs_before_a_sustained_read_backlog_can_starve_it() -> None:
    holder: dict[str, Any] = {}
    worker = _worker(
        holder,
        max_queue_size=8,
        maintenance_interval_seconds=0.05,
        block_read=True,
    )
    reads: list[asyncio.Task[Any]] = []
    first_read: asyncio.Task[Any] | None = None
    try:
        await worker.start()
        first_read = asyncio.create_task(worker.read_account("account-blocking"))
        await _wait_thread_event(holder["session"].read_entered)
        reads = [asyncio.create_task(worker.read_account(f"account-{index}")) for index in range(8)]
        await asyncio.sleep(0)
        # Hold the owner in its first read until the configured deadline has
        # actually elapsed, with a full backlog already waiting behind it.
        await asyncio.sleep(0.08)
        holder["session"].release_read.set()
        await first_read
        await asyncio.gather(*reads)
        await worker.aclose()

        names = [name for name, _, _ in holder["session"].calls]
        blocking_read = names.index("read_account")
        second_read = names.index("read_account", blocking_read + 1)
        maintenance = names.index("maintain")
        assert blocking_read < maintenance < second_read
    finally:
        await _cleanup_worker(worker, holder, tasks=(first_read, *reads))


@_run_async
async def test_blocking_read_does_not_block_the_async_event_loop() -> None:
    holder: dict[str, Any] = {}
    worker = _worker(holder, block_read=True)
    read_task: asyncio.Task[Any] | None = None
    try:
        await worker.start()

        read_task = asyncio.create_task(worker.read_account("account-a"))
        await _wait_thread_event(holder["session"].read_entered)
        ticks = 0
        for _ in range(5):
            await asyncio.sleep(0.001)
            ticks += 1
        assert ticks == 5

        holder["session"].release_read.set()
        await read_task
        await worker.aclose()
    finally:
        await _cleanup_worker(worker, holder, tasks=(read_task,))


@_run_async
async def test_queue_is_bounded_and_cancelled_pending_request_is_skipped() -> None:
    holder: dict[str, Any] = {}
    worker = _worker(holder, max_queue_size=1, block_read=True)
    running: asyncio.Task[Any] | None = None
    pending: asyncio.Task[Any] | None = None
    try:
        await worker.start()

        running = asyncio.create_task(worker.read_account("running"))
        await _wait_thread_event(holder["session"].read_entered)
        pending = asyncio.create_task(worker.read_order("orders-a", "cancel-me"))
        await asyncio.sleep(0)
        with pytest.raises(ServiceReadWorkerError) as full:
            await worker.read_strategy_health("health-a")
        assert full.value.code == "QUEUE_FULL"

        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        await asyncio.sleep(0)
        holder["session"].release_read.set()
        await running
        await worker.aclose()

        assert [name for name, _, _ in holder["session"].calls].count("read_order") == 0
        assert worker._thread is not None and not worker._thread.is_alive()
    finally:
        await _cleanup_worker(worker, holder, tasks=(running, pending))


@_run_async
async def test_close_rejects_new_work_and_fails_queued_work_before_joining() -> None:
    holder: dict[str, Any] = {}
    worker = _worker(holder, max_queue_size=2, block_read=True)
    running: asyncio.Task[Any] | None = None
    pending: asyncio.Task[Any] | None = None
    close_task: asyncio.Task[Any] | None = None
    try:
        await worker.start()

        running = asyncio.create_task(worker.read_account("running"))
        await _wait_thread_event(holder["session"].read_entered)
        pending = asyncio.create_task(worker.read_order("orders-a", "pending"))
        await asyncio.sleep(0)
        close_task = asyncio.create_task(worker.aclose())
        with pytest.raises(ServiceReadWorkerError) as pending_error:
            await pending
        assert pending_error.value.code == "CLOSED"
        with pytest.raises(ServiceReadWorkerError) as rejected:
            await worker.read_strategy_health("health-a")
        assert rejected.value.code == "CLOSED"
        assert not close_task.done()

        holder["session"].release_read.set()
        await running
        await close_task
        assert [name for name, _, _ in holder["session"].calls].count("read_order") == 0
        assert worker._thread is not None and not worker._thread.is_alive()
    finally:
        await _cleanup_worker(
            worker,
            holder,
            tasks=(running, pending),
            close_task=close_task,
        )


@_run_async
async def test_start_failure_is_reported_and_session_is_closed_on_owner_thread() -> None:
    holder: dict[str, Any] = {}
    worker = _worker(holder, start_error=True)

    try:
        with pytest.raises(ServiceReadWorkerError) as failure:
            await worker.start()
        assert failure.value.code == "START_FAILED"
        await worker.aclose()

        names = [name for name, _, _ in holder["session"].calls]
        assert names == ["start", "close"]
        assert holder["session"].calls[0][1] == holder["session"].calls[-1][1]
        assert worker._thread is not None and not worker._thread.is_alive()
    finally:
        await _cleanup_worker(worker, holder)


@_run_async
async def test_maintenance_failure_is_reported_and_owner_thread_stops() -> None:
    holder: dict[str, Any] = {}
    worker = _worker(holder, maintain_error=True, maintenance_interval_seconds=0.01)
    try:
        await worker.start()
        await asyncio.sleep(0.04)

        with pytest.raises(ServiceReadWorkerError) as read_failure:
            await worker.read_account("account-a")
        assert read_failure.value.code == "MAINTAIN_FAILED"
        with pytest.raises(ServiceReadWorkerError) as close_failure:
            await worker.aclose()
        assert close_failure.value.code == "MAINTAIN_FAILED"
        names = [name for name, _, _ in holder["session"].calls]
        assert names == ["start", "maintain", "close"]
        assert worker._thread is not None and not worker._thread.is_alive()
    finally:
        await _cleanup_worker(worker, holder)


@_run_async
async def test_close_failure_is_reported_after_owner_thread_terminates() -> None:
    holder: dict[str, Any] = {}
    worker = _worker(holder, close_error=True)
    try:
        await worker.start()

        with pytest.raises(ServiceReadWorkerError) as failure:
            await worker.aclose()
        assert failure.value.code == "CLOSE_FAILED"
        assert [name for name, _, _ in holder["session"].calls] == ["start", "close"]
        assert worker._thread is not None and not worker._thread.is_alive()
    finally:
        await _cleanup_worker(worker, holder)


@_run_async
async def test_process_control_and_stop_iteration_read_failures_are_finite() -> None:
    for error_type in (StopIteration, KeyboardInterrupt, SystemExit):
        holder: dict[str, Any] = {}
        worker = _worker(holder, read_error=error_type)
        try:
            await worker.start()
            with pytest.raises(ServiceReadWorkerError) as failure:
                await worker.read_account("account-a")
            assert failure.value.code == "READ_FAILED"
            assert await worker.read_account("account-a") == (
                "read_account",
                ("account-a", None),
            )
            await worker.aclose()
            assert worker._thread is not None and not worker._thread.is_alive()
        finally:
            await _cleanup_worker(worker, holder)


@_run_async
async def test_close_during_startup_makes_start_fail_and_closes_on_owner_thread() -> None:
    holder: dict[str, Any] = {}
    worker = _worker(holder, block_start=True)
    start_task: asyncio.Task[Any] | None = None
    close_task: asyncio.Task[Any] | None = None
    try:
        start_task = asyncio.create_task(worker.start())
        await _wait_thread_event(holder["factory_created"])
        await _wait_thread_event(holder["session"].start_entered)
        close_task = asyncio.create_task(worker.aclose())
        await asyncio.sleep(0)
        holder["session"].release_start.set()

        with pytest.raises(ServiceReadWorkerError) as failure:
            await start_task
        assert failure.value.code == "CLOSED"
        await close_task
        names = [name for name, _, _ in holder["session"].calls]
        assert names == ["start", "close"]
        assert holder["factory_thread_id"] == holder["session"].calls[0][1]
        assert holder["session"].calls[0][1] == holder["session"].calls[-1][1]
        assert worker._thread is not None and not worker._thread.is_alive()
    finally:
        await _cleanup_worker(
            worker,
            holder,
            tasks=(start_task,),
            close_task=close_task,
        )


@_run_async
async def test_construction_and_close_before_start_create_no_session_or_thread() -> None:
    calls: list[str] = []

    def factory() -> _Session:
        calls.append("factory")
        raise AssertionError("factory must not run before start")

    worker = ServiceReadWorker(factory)
    assert worker._thread is None
    await worker.aclose()
    assert worker._thread is None
    assert calls == []
    with pytest.raises(ServiceReadWorkerError) as closed:
        await worker.start()
    assert closed.value.code == "CLOSED"
