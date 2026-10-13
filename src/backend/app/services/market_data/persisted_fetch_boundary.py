"""Strict boundaries for receipt-producing market-data store operations."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from datetime import datetime, timezone
from typing import Protocol, TypeVar

from app.services.market_data.store import PersistedProviderFetch

_TaskResult = TypeVar("_TaskResult")
_Error = TypeVar("_Error", bound=Exception)
_CancellationError = TypeVar("_CancellationError", bound=BaseException)
_UTC = timezone.utc


class PersistedProviderFetchBoundaryError(TypeError):
    """Raised when a store operation returns before a receipt is query-visible."""


class UtcParser(Protocol):
    """A collector-specific parser for one timestamp field."""

    def __call__(self, value: object, *, field_name: str) -> datetime: ...


def find_cancellation_error(
    error: BaseException,
    error_type: type[_CancellationError],
) -> _CancellationError | None:
    """Find a typed cancellation outcome retained in an exception chain.

    Python 3.10 may expose a plain ``CancelledError`` when awaiting a task
    whose coroutine raised a ``CancelledError`` subclass. The original typed
    outcome remains linked through ``__cause__`` or ``__context__``.
    """
    pending = [error]
    visited: set[int] = set()
    while pending:
        current = pending.pop()
        current_id = id(current)
        if current_id in visited:
            continue
        visited.add(current_id)
        if isinstance(current, error_type):
            return current
        if current.__cause__ is not None:
            pending.append(current.__cause__)
        if current.__context__ is not None:
            pending.append(current.__context__)
    return None


def require_persisted_provider_fetch(receipt: object) -> PersistedProviderFetch:
    """Return only a durable, query-visible provider receipt."""
    if not isinstance(receipt, PersistedProviderFetch):
        raise PersistedProviderFetchBoundaryError(
            "store operation did not return a persisted provider fetch"
        )
    return receipt


def require_lower_sha256(
    value: object,
    *,
    code: str,
    error_type: type[_Error],
) -> str:
    """Validate a collector digest while preserving its public error type."""
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise error_type(code)
    return value


def utc_parser(error_type: type[Exception], code: str) -> UtcParser:
    """Build a UTC parser that keeps its collector's timestamp error mapping."""

    def parse(value: object, *, field_name: str) -> datetime:
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise error_type(code)
        return value.astimezone(_UTC)

    return parse


async def persist_provider_fetch(
    persistence: Awaitable[object],
) -> PersistedProviderFetch:
    """Await one store operation and reject deferred or unrecognized receipts."""
    return require_persisted_provider_fetch(await persistence)


async def await_task_after_cancellation(task: asyncio.Task[_TaskResult]) -> _TaskResult:
    """Complete a shielded critical task despite repeated caller cancellation."""
    while True:
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            if task.done():
                return task.result()


async def _await_persistence_after_cancellation(
    task: asyncio.Task[_TaskResult],
) -> _TaskResult:
    """Keep the persistence wait seam while sharing cancellation handling."""
    return await await_task_after_cancellation(task)


async def _await_lease_release_after_cancellation(
    task: asyncio.Task[_TaskResult],
) -> _TaskResult:
    """Keep the lease-release wait seam while sharing cancellation handling."""
    return await await_task_after_cancellation(task)


def utc_now() -> datetime:
    """Return the current aware UTC timestamp used for local receipts."""
    return datetime.now(_UTC)
