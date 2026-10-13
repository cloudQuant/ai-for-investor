"""Compatibility contracts for the extracted market-data store boundaries."""

from __future__ import annotations

import inspect
from datetime import datetime, timezone
from types import ModuleType

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.market_data import (
    store_calendar,
    store_evidence,
    store_persistence,
    store_projection,
)
from app.services.market_data.store import MarketDataStore, MarketDataStoreError


@pytest.mark.parametrize(
    ("module", "function_name", "method_name", "args", "kwargs"),
    [
        (
            store_persistence,
            "persist_provider_result",
            "persist_provider_result",
            (object(), object()),
            {},
        ),
        (
            store_evidence,
            "ensure_provider_active",
            "ensure_provider_active",
            ("provider:example",),
            {},
        ),
        (
            store_calendar,
            "read_calendar",
            "read_calendar",
            (),
            {"calendar_code": "CN-SSE", "window": object()},
        ),
        (
            store_projection,
            "read_observations",
            "read_observations",
            (object(),),
            {"knowledge_cutoff": datetime(2026, 10, 12, tzinfo=timezone.utc)},
        ),
    ],
)
async def test_facade_preserves_store_errors_across_extracted_boundaries(
    monkeypatch: pytest.MonkeyPatch,
    module: ModuleType,
    function_name: str,
    method_name: str,
    args: tuple[object, ...],
    kwargs: dict[str, object],
) -> None:
    """Errors raised by an extracted implementation retain their public code."""

    def fail(*_args: object, **_kwargs: object) -> None:
        raise MarketDataStoreError("STORE_BOUNDARY_FAILURE")

    monkeypatch.setattr(module, function_name, fail)
    store = MarketDataStore(AsyncSession())

    with pytest.raises(MarketDataStoreError) as rejected:
        await getattr(store, method_name)(*args, **kwargs)

    assert rejected.value.code == "STORE_BOUNDARY_FAILURE"


def test_provider_persistence_facade_keeps_its_call_signature() -> None:
    """Existing callers can continue using the same provider-write arguments."""

    parameters = inspect.signature(MarketDataStore.persist_provider_result).parameters

    assert tuple(parameters) == (
        "self",
        "context",
        "result",
        "received_at",
        "source_authorization",
        "unverified_compatibility_reason",
        "fetch_lease",
        "deferred_intent",
    )
    assert inspect.iscoroutinefunction(MarketDataStore.persist_provider_result)
