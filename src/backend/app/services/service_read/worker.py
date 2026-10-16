"""Single-thread owner for authorized service reads and manual submission.

The composition root supplies a trusted session factory.  The factory and
every session method run on one dedicated, non-daemon thread so runtimes and
clients with thread affinity stay together.  This module intentionally imports
no service SDK or application composition code.
"""

from __future__ import annotations

import asyncio
import math
import queue
import threading
import time
from collections.abc import Callable
from enum import Enum, auto
from typing import TYPE_CHECKING, Any, Protocol, TypeVar

if TYPE_CHECKING:
    from app.services.service_read.contracts import (
        AccountBookReadView,
        AccountReadView,
        OrderReadView,
        StrategyHealthView,
    )
    from app.services.service_read.gateway_health import GatewayHealthView

__all__ = ["ServiceReadSession", "ServiceReadWorker", "ServiceReadWorkerError"]

_Result = TypeVar("_Result")
_STOP = object()


class ServiceReadWorkerError(RuntimeError):
    """Finite lifecycle or queue-admission failure from the owner worker."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class ServiceReadSession(Protocol):
    """Synchronous session whose complete lifecycle belongs to one thread.

    A trusted factory may create the SDK runtime and authorized client here;
    ``start`` starts the runtime, ``maintain`` renews/maintains it, and ``close``
    releases it.  Implementations must keep all of that work synchronous so
    this worker can preserve one owner thread from construction through close.
    """

    def start(self) -> None: ...

    def maintain(self) -> None: ...

    def read_account(self, account_ref: str, *, currency: str | None = None) -> AccountReadView: ...

    def read_gateway_health(self, account_ref: str) -> GatewayHealthView: ...

    def read_account_book(self, account_ref: str) -> AccountBookReadView: ...

    def read_order(self, scope_ref: str, intent_id: str) -> OrderReadView: ...

    def read_strategy_health(self, scope_ref: str) -> StrategyHealthView: ...

    def submit_manual_order(self, scope_ref: str, arguments: dict[str, Any]) -> Any: ...

    def submit_paper_order(self, scope_ref: str, arguments: dict[str, Any]) -> Any: ...

    def submit_approved_target(self, scope_ref: str, arguments: dict[str, Any]) -> Any: ...

    def upload_portfolio_analytics_input(
        self, scope_ref: str, input_snapshot_id: str, facts: dict[str, Any]
    ) -> Any: ...

    def submit_portfolio_analytics_task(
        self, scope_ref: str, task_ref: str, input_snapshot_id: str, request: dict[str, Any]
    ) -> Any: ...

    def query_portfolio_analytics_task(self, scope_ref: str, task_ref: str) -> Any: ...

    def cancel_portfolio_analytics_task(self, scope_ref: str, task_ref: str) -> Any: ...

    def close(self) -> None: ...


class _State(Enum):
    NEW = auto()
    STARTING = auto()
    RUNNING = auto()
    CLOSING = auto()
    CLOSED = auto()
    FAILED = auto()


class _Kind(Enum):
    ACCOUNT = auto()
    GATEWAY_HEALTH = auto()
    ACCOUNT_BOOK = auto()
    ORDER = auto()
    STRATEGY_HEALTH = auto()
    MANUAL_ORDER = auto()
    PAPER_ORDER = auto()
    APPROVED_TARGET = auto()
    ANALYTICS_INPUT = auto()
    ANALYTICS_SUBMIT = auto()
    ANALYTICS_QUERY = auto()
    ANALYTICS_CANCEL = auto()


class _Request:
    __slots__ = ("kind", "arguments", "future", "cancelled")

    def __init__(
        self,
        kind: _Kind,
        arguments: tuple[Any, ...],
        future: asyncio.Future[Any],
    ) -> None:
        self.kind = kind
        self.arguments = arguments
        self.future = future
        self.cancelled = threading.Event()


class ServiceReadWorker:
    """Dispatch bounded configured work through one session-owning thread.

    Construction is inert. ``start`` creates the thread and resolves only
    after factory/session startup completes. Reads and explicitly configured
    manual or paper-order operations enqueue fixed operations. Application
    routes remain responsible for authenticating and authorizing each request.
    """

    def __init__(
        self,
        session_factory: Callable[[], ServiceReadSession],
        *,
        max_queue_size: int = 32,
        maintenance_interval_seconds: float = 1.0,
        name: str = "service-read-owner",
    ) -> None:
        if not callable(session_factory):
            raise TypeError("session_factory must be callable")
        if type(max_queue_size) is not int or max_queue_size < 1:
            raise ValueError("max_queue_size must be a positive integer")
        if (
            isinstance(maintenance_interval_seconds, bool)
            or not isinstance(maintenance_interval_seconds, (int, float))
            or not math.isfinite(maintenance_interval_seconds)
            or maintenance_interval_seconds <= 0
        ):
            raise ValueError("maintenance_interval_seconds must be finite and positive")
        if type(name) is not str or not name or name != name.strip():
            raise ValueError("name must be a non-empty trimmed string")

        self._factory = session_factory
        self._maintenance_interval = float(maintenance_interval_seconds)
        self._name = name
        self._state = _State.NEW
        self._lock = threading.Lock()
        self._requests: queue.Queue[_Request | object] = queue.Queue(maxsize=max_queue_size)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._startup_done: asyncio.Future[None] | None = None
        self._thread_done: asyncio.Future[None] | None = None
        self._thread: threading.Thread | None = None
        self._start_code: str | None = None
        self._maintain_failed = False
        self._close_failed = False
        self._close_requested = False

    async def start(self) -> None:
        """Start the owner thread and wait for session startup to finish."""

        loop = asyncio.get_running_loop()
        thread_to_start: threading.Thread | None = None
        with self._lock:
            if self._state is _State.NEW:
                self._loop = loop
                self._startup_done = loop.create_future()
                self._thread_done = loop.create_future()
                self._state = _State.STARTING
                thread_to_start = threading.Thread(
                    target=self._run_owner,
                    name=self._name,
                    daemon=False,
                )
                self._thread = thread_to_start
            elif self._state is _State.FAILED:
                code = "MAINTAIN_FAILED" if self._maintain_failed else "START_FAILED"
                raise ServiceReadWorkerError(code)
            elif self._state in {_State.CLOSING, _State.CLOSED}:
                raise ServiceReadWorkerError("CLOSED")
            elif self._loop is not loop:
                raise ServiceReadWorkerError("WRONG_EVENT_LOOP")
            startup_done = self._startup_done

        if thread_to_start is not None:
            try:
                thread_to_start.start()
            except Exception:
                with self._lock:
                    self._start_code = "START_FAILED"
                    self._state = _State.FAILED
                self._signal_future(self._startup_done)
                self._signal_future(self._thread_done)

        if startup_done is None:
            raise ServiceReadWorkerError("START_FAILED")
        await asyncio.shield(startup_done)
        with self._lock:
            start_code = self._start_code
            state = self._state
            maintain_failed = self._maintain_failed
        if start_code is not None:
            raise ServiceReadWorkerError(start_code)
        if state is _State.FAILED:
            raise ServiceReadWorkerError("MAINTAIN_FAILED" if maintain_failed else "START_FAILED")
        if state is not _State.RUNNING:
            raise ServiceReadWorkerError("CLOSED")

    async def read_account(
        self, account_ref: str, *, currency: str | None = None
    ) -> AccountReadView:
        return await self._submit(_Kind.ACCOUNT, account_ref, currency)

    async def read_gateway_health(self, account_ref: str) -> GatewayHealthView:
        """Queue the paired status and account reads on the existing owner thread."""

        return await self._submit(_Kind.GATEWAY_HEALTH, account_ref)

    async def read_order(self, scope_ref: str, intent_id: str) -> OrderReadView:
        return await self._submit(_Kind.ORDER, scope_ref, intent_id)

    async def read_account_book(self, account_ref: str) -> AccountBookReadView:
        return await self._submit(_Kind.ACCOUNT_BOOK, account_ref)

    async def read_strategy_health(self, scope_ref: str) -> StrategyHealthView:
        return await self._submit(_Kind.STRATEGY_HEALTH, scope_ref)

    async def submit_manual_order(self, scope_ref: str, arguments: dict[str, Any]) -> Any:
        """Queue a deployment-authorized manual submit on the session owner thread."""

        return await self._submit(_Kind.MANUAL_ORDER, scope_ref, arguments)

    async def submit_paper_order(self, scope_ref: str, arguments: dict[str, Any]) -> Any:
        """Queue one paper-owner order on the existing SDK owner thread."""

        return await self._submit(_Kind.PAPER_ORDER, scope_ref, arguments)

    async def submit_approved_target(
        self, scope_ref: str, arguments: dict[str, Any]
    ) -> Any:
        """Queue one approved target on the existing SDK owner thread."""

        return await self._submit(_Kind.APPROVED_TARGET, scope_ref, arguments)

    async def upload_portfolio_analytics_input(
        self, scope_ref: str, input_snapshot_id: str, facts: dict[str, Any]
    ) -> Any:
        return await self._submit(
            _Kind.ANALYTICS_INPUT, scope_ref, input_snapshot_id, facts
        )

    async def submit_portfolio_analytics_task(
        self, scope_ref: str, task_ref: str, input_snapshot_id: str, request: dict[str, Any]
    ) -> Any:
        return await self._submit(
            _Kind.ANALYTICS_SUBMIT, scope_ref, task_ref, input_snapshot_id, request
        )

    async def query_portfolio_analytics_task(self, scope_ref: str, task_ref: str) -> Any:
        return await self._submit(_Kind.ANALYTICS_QUERY, scope_ref, task_ref)

    async def cancel_portfolio_analytics_task(self, scope_ref: str, task_ref: str) -> Any:
        return await self._submit(_Kind.ANALYTICS_CANCEL, scope_ref, task_ref)

    async def aclose(self) -> None:
        """Reject new reads, discard queued reads, and close on the owner thread."""

        loop = asyncio.get_running_loop()
        with self._lock:
            if self._state is _State.NEW:
                self._state = _State.CLOSED
                return
            if self._state is _State.CLOSED and self._thread is None:
                return
            if self._loop is not loop:
                raise ServiceReadWorkerError("WRONG_EVENT_LOOP")
            thread_done = self._thread_done
            if self._state in {_State.STARTING, _State.RUNNING} and not self._close_requested:
                self._state = _State.CLOSING
                self._close_requested = True
                self._fail_queued_locked("CLOSED")
                # Draining above guarantees room for this wakeup marker.
                self._requests.put_nowait(_STOP)

        if thread_done is not None:
            await asyncio.shield(thread_done)
        thread = self._thread
        while thread is not None and thread.is_alive():
            # The owner signals from its finalizer immediately before returning.
            # Yield once more so aclose also guarantees the non-daemon thread is gone.
            await asyncio.sleep(0)

        with self._lock:
            close_failed = self._close_failed
            maintain_failed = self._maintain_failed
        if close_failed:
            raise ServiceReadWorkerError("CLOSE_FAILED")
        if maintain_failed:
            raise ServiceReadWorkerError("MAINTAIN_FAILED")

    async def _submit(self, kind: _Kind, *arguments: Any) -> _Result:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[_Result] = loop.create_future()
        request = _Request(kind, arguments, future)
        future.add_done_callback(
            lambda completed: request.cancelled.set() if completed.cancelled() else None
        )
        with self._lock:
            if self._state in {_State.CLOSING, _State.CLOSED}:
                raise ServiceReadWorkerError("CLOSED")
            if self._state is _State.FAILED:
                code = "MAINTAIN_FAILED" if self._maintain_failed else "START_FAILED"
                raise ServiceReadWorkerError(code)
            if self._loop is not loop:
                code = "NOT_STARTED" if self._loop is None else "WRONG_EVENT_LOOP"
                raise ServiceReadWorkerError(code)
            if self._state is not _State.RUNNING:
                raise ServiceReadWorkerError("NOT_STARTED")
            try:
                self._requests.put_nowait(request)
            except queue.Full:
                raise ServiceReadWorkerError("QUEUE_FULL") from None
        try:
            return await future
        except asyncio.CancelledError:
            request.cancelled.set()
            raise

    def _run_owner(self) -> None:
        session: ServiceReadSession | None = None
        startup_signaled = False
        try:
            session = self._factory()
            session.start()
            with self._lock:
                if self._state is _State.STARTING:
                    self._state = _State.RUNNING
            self._signal_future(self._startup_done)
            startup_signaled = True
            next_maintenance = time.monotonic() + self._maintenance_interval

            while True:
                with self._lock:
                    if self._state in {_State.CLOSING, _State.CLOSED, _State.FAILED}:
                        break
                if time.monotonic() >= next_maintenance:
                    try:
                        session.maintain()
                    except BaseException:
                        with self._lock:
                            self._maintain_failed = True
                            self._state = _State.FAILED
                            self._fail_queued_locked("MAINTAIN_FAILED")
                        break
                    next_maintenance = time.monotonic() + self._maintenance_interval

                timeout = max(0.0, next_maintenance - time.monotonic())
                try:
                    item = self._requests.get(timeout=timeout)
                except queue.Empty:
                    continue
                if item is _STOP:
                    break
                request = item
                assert isinstance(request, _Request)
                with self._lock:
                    closing = self._state is _State.CLOSING
                if closing:
                    self._deliver_error(request, ServiceReadWorkerError("CLOSED"))
                elif not request.cancelled.is_set():
                    cancelled = self._claim_request(request)
                    with self._lock:
                        current_state = self._state
                        closing = current_state is _State.CLOSING
                        failed_code = (
                            "MAINTAIN_FAILED"
                            if self._maintain_failed
                            else "START_FAILED"
                            if current_state is _State.FAILED
                            else None
                        )
                    if closing:
                        self._deliver_error(request, ServiceReadWorkerError("CLOSED"))
                    elif failed_code is not None:
                        self._deliver_error(request, ServiceReadWorkerError(failed_code))
                    elif request.cancelled.is_set():
                        # This covers a loop shutdown during the cancellation
                        # handshake; canceled futures are already complete.
                        if not request.future.cancelled():
                            self._deliver_error(request, ServiceReadWorkerError("CLOSED"))
                    elif not cancelled:
                        self._dispatch(session, request)
        except BaseException:
            with self._lock:
                if not startup_signaled:
                    self._start_code = "START_FAILED"
                    self._state = _State.FAILED
                self._fail_queued_locked(
                    "START_FAILED" if not startup_signaled else "MAINTAIN_FAILED"
                )
            if not startup_signaled:
                self._signal_future(self._startup_done)
                startup_signaled = True
            elif not self._maintain_failed:
                with self._lock:
                    self._maintain_failed = True
                    self._state = _State.FAILED
        finally:
            if session is not None:
                try:
                    session.close()
                except BaseException:
                    with self._lock:
                        self._close_failed = True
            with self._lock:
                if self._state not in {_State.FAILED, _State.CLOSED}:
                    self._state = _State.CLOSED
                pending_code = (
                    "MAINTAIN_FAILED"
                    if self._maintain_failed
                    else "START_FAILED"
                    if self._start_code is not None
                    else "CLOSED"
                )
                self._fail_queued_locked(pending_code)
            if not startup_signaled:
                self._signal_future(self._startup_done)
            self._signal_future(self._thread_done)

    def _dispatch(self, session: ServiceReadSession, request: _Request) -> None:
        try:
            if request.kind is _Kind.ACCOUNT:
                result = session.read_account(request.arguments[0], currency=request.arguments[1])
            elif request.kind is _Kind.GATEWAY_HEALTH:
                result = session.read_gateway_health(request.arguments[0])
            elif request.kind is _Kind.ACCOUNT_BOOK:
                result = session.read_account_book(request.arguments[0])
            elif request.kind is _Kind.ORDER:
                result = session.read_order(request.arguments[0], request.arguments[1])
            elif request.kind is _Kind.MANUAL_ORDER:
                result = session.submit_manual_order(
                    request.arguments[0], request.arguments[1]
                )
            elif request.kind is _Kind.PAPER_ORDER:
                result = session.submit_paper_order(
                    request.arguments[0], request.arguments[1]
                )
            elif request.kind is _Kind.APPROVED_TARGET:
                result = session.submit_approved_target(
                    request.arguments[0], request.arguments[1]
                )
            elif request.kind is _Kind.ANALYTICS_INPUT:
                result = session.upload_portfolio_analytics_input(
                    request.arguments[0], request.arguments[1], request.arguments[2]
                )
            elif request.kind is _Kind.ANALYTICS_SUBMIT:
                result = session.submit_portfolio_analytics_task(
                    request.arguments[0],
                    request.arguments[1],
                    request.arguments[2],
                    request.arguments[3],
                )
            elif request.kind is _Kind.ANALYTICS_QUERY:
                result = session.query_portfolio_analytics_task(
                    request.arguments[0], request.arguments[1]
                )
            elif request.kind is _Kind.ANALYTICS_CANCEL:
                result = session.cancel_portfolio_analytics_task(
                    request.arguments[0], request.arguments[1]
                )
            else:
                result = session.read_strategy_health(request.arguments[0])
        except Exception as error:
            if isinstance(error, StopIteration):
                self._deliver_error(request, ServiceReadWorkerError("READ_FAILED"))
            else:
                self._deliver_error(request, error)
        except BaseException:
            # Sync session code must never let process-control exceptions escape
            # the owner loop or pass an unraisable exception to an asyncio Future.
            self._deliver_error(request, ServiceReadWorkerError("READ_FAILED"))
        else:
            self._deliver_result(request, result)

    def _claim_request(self, request: _Request) -> bool:
        """Read cancellation state on its event loop before starting the RPC."""

        if request.cancelled.is_set():
            return True
        loop = self._loop
        if loop is None:
            return True
        checked = threading.Event()

        def check() -> None:
            if request.future.cancelled():
                request.cancelled.set()
            checked.set()

        try:
            loop.call_soon_threadsafe(check)
        except RuntimeError:
            request.cancelled.set()
            return True
        while not checked.wait(timeout=0.05):
            with self._lock:
                closing = self._state in {_State.CLOSING, _State.CLOSED, _State.FAILED}
            if closing or loop.is_closed():
                request.cancelled.set()
                return True
        return request.cancelled.is_set()

    def _fail_queued_locked(self, code: str) -> None:
        while True:
            try:
                item = self._requests.get_nowait()
            except queue.Empty:
                return
            if isinstance(item, _Request):
                self._deliver_error(item, ServiceReadWorkerError(code))

    def _deliver_result(self, request: _Request, result: Any) -> None:
        self._schedule_completion(request.future, result=result)

    def _deliver_error(self, request: _Request, error: BaseException) -> None:
        self._schedule_completion(request.future, error=error)

    def _schedule_completion(
        self,
        future: asyncio.Future[Any] | None,
        *,
        result: Any = None,
        error: BaseException | None = None,
    ) -> None:
        loop = self._loop
        if future is None or loop is None:
            return

        def complete() -> None:
            if future.done():
                return
            if error is not None:
                future.set_exception(error)
            else:
                future.set_result(result)

        try:
            loop.call_soon_threadsafe(complete)
        except RuntimeError:
            # The application loop has already gone away; session teardown still
            # proceeds on the owner thread and cannot be made observable there.
            return

    def _signal_future(self, future: asyncio.Future[None] | None) -> None:
        self._schedule_completion(future, result=None)
