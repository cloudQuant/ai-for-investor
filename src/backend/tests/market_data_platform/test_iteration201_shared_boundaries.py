"""Failure boundaries shared by Iteration 201 market-data and holdout services."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from sqlalchemy import CursorResult, Result, create_engine, text

from app.db.persistence_boundaries import (
    cursor_rowcount,
    is_holdout_sha256,
    is_lower_hex_sha256,
    optional_stored_utc,
    stored_utc,
)
from app.services.market_data.persisted_fetch_boundary import (
    PersistedProviderFetchBoundaryError,
    persist_provider_fetch,
    require_lower_sha256,
    require_persisted_provider_fetch,
    utc_parser,
)
from app.services.market_data.publication import MarketDataDeferredPublicationIntent
from app.services.market_data.store import DeferredProviderFetch, PersistedProviderFetch

UTC = timezone.utc
_RECEIVED_AT = datetime(2026, 10, 12, 8, 0, tzinfo=UTC)


def _persisted_fetch() -> PersistedProviderFetch:
    return PersistedProviderFetch(
        series_id="series-test",
        source_snapshot_id="snapshot-test",
        observation_revision_ids=("revision-test",),
        passing_observation_count=1,
        failed_observation_count=0,
        received_at=_RECEIVED_AT,
    )


def _deferred_fetch() -> DeferredProviderFetch:
    return DeferredProviderFetch(
        series_id="series-test",
        source_snapshot_id="snapshot-test",
        publication_id="publication-test",
        observation_revision_ids=("revision-test",),
        passing_observation_count=1,
        failed_observation_count=0,
        local_received_at=_RECEIVED_AT,
        intent=MarketDataDeferredPublicationIntent(
            workflow_kind="legacy_stock_daily_import",
            intent_sha256="a" * 64,
        ),
    )


def test_persisted_fetch_boundary_accepts_only_query_visible_receipts() -> None:
    receipt = _persisted_fetch()

    assert require_persisted_provider_fetch(receipt) is receipt
    with pytest.raises(PersistedProviderFetchBoundaryError):
        require_persisted_provider_fetch(_deferred_fetch())


@pytest.mark.asyncio
async def test_persist_provider_fetch_rejects_a_deferred_store_result() -> None:
    async def deferred_result() -> DeferredProviderFetch:
        return _deferred_fetch()

    with pytest.raises(PersistedProviderFetchBoundaryError):
        await persist_provider_fetch(deferred_result())


def test_shared_digest_validation_keeps_the_callers_error_mapping() -> None:
    class CollectorError(ValueError):
        def __init__(self, code: str) -> None:
            self.code = code
            super().__init__(code)

    digest = "a" * 64
    assert (
        require_lower_sha256(
            digest,
            code="TEST_DIGEST_INVALID",
            error_type=CollectorError,
        )
        == digest
    )
    with pytest.raises(CollectorError, match="^TEST_DIGEST_INVALID$") as rejected:
        require_lower_sha256(
            "A" * 64,
            code="TEST_DIGEST_INVALID",
            error_type=CollectorError,
        )
    assert rejected.value.code == "TEST_DIGEST_INVALID"
    assert is_lower_hex_sha256(digest)
    assert not is_lower_hex_sha256("A" * 64)
    assert is_holdout_sha256(digest)
    assert not is_holdout_sha256("A" * 64)


def test_shared_timestamp_parser_keeps_the_callers_error_mapping() -> None:
    class CollectorError(ValueError):
        def __init__(self, code: str) -> None:
            self.code = code
            super().__init__(code)

    parse_timestamp = utc_parser(CollectorError, "TEST_TIMESTAMP_INVALID")
    assert parse_timestamp(_RECEIVED_AT, field_name="captured_at") == _RECEIVED_AT

    with pytest.raises(CollectorError, match="^TEST_TIMESTAMP_INVALID$") as rejected:
        parse_timestamp(datetime(2026, 10, 12, 8, 0), field_name="captured_at")
    assert rejected.value.code == "TEST_TIMESTAMP_INVALID"


def test_cursor_rowcount_is_zero_without_a_cursor_and_reads_dml_count() -> None:
    result = MagicMock(spec=Result)
    assert not hasattr(result, "rowcount")
    assert cursor_rowcount(result) == 0

    engine = create_engine("sqlite:///:memory:")
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE rowcount_probe (id INTEGER PRIMARY KEY)"))
            connection.execute(text("INSERT INTO rowcount_probe (id) VALUES (1)"))
            updated = connection.execute(text("UPDATE rowcount_probe SET id = 2 WHERE id = 1"))
            assert isinstance(updated, CursorResult)
            assert cursor_rowcount(updated) == 1
    finally:
        engine.dispose()


def test_stored_utc_normalization_preserves_naive_and_null_semantics() -> None:
    naive = datetime(2026, 10, 12, 8, 0)

    assert stored_utc(naive) == naive.replace(tzinfo=UTC)
    assert stored_utc(naive.replace(tzinfo=timezone(timedelta(hours=8)))) == datetime(
        2026, 10, 12, 0, 0, tzinfo=UTC
    )
    assert optional_stored_utc(None) is None
