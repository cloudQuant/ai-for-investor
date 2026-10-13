"""Contracts for durable market-data task and cancellation boundaries."""

from __future__ import annotations

import asyncio

from app.services.market_data.persisted_fetch_boundary import find_cancellation_error


class _TypedPartialCancellation(asyncio.CancelledError):
    """One typed cancellation outcome used to verify exception-chain recovery."""


def test_find_cancellation_error_returns_a_direct_match() -> None:
    cancellation = _TypedPartialCancellation("partial publication")

    assert find_cancellation_error(cancellation, _TypedPartialCancellation) is cancellation


def test_find_cancellation_error_recovers_python310_task_context() -> None:
    cancellation = _TypedPartialCancellation("partial publication")
    task_boundary_error = asyncio.CancelledError()
    task_boundary_error.__context__ = cancellation

    assert find_cancellation_error(task_boundary_error, _TypedPartialCancellation) is cancellation


def test_find_cancellation_error_traverses_explicit_causes() -> None:
    cancellation = _TypedPartialCancellation("partial publication")
    wrapper_error = RuntimeError("wrapper")
    wrapper_error.__cause__ = cancellation

    assert find_cancellation_error(wrapper_error, _TypedPartialCancellation) is cancellation


def test_find_cancellation_error_returns_none_without_a_match() -> None:
    error = asyncio.CancelledError("ordinary cancellation")

    assert find_cancellation_error(error, _TypedPartialCancellation) is None


def test_find_cancellation_error_stops_on_exception_chain_cycles() -> None:
    first = RuntimeError("first")
    second = ValueError("second")
    first.__context__ = second
    second.__cause__ = first

    assert find_cancellation_error(first, _TypedPartialCancellation) is None
