"""Publication identity pairing checks for synthetic OpenData index snapshots."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import pytest

from app.services.risk_analytics.opendata_index_benchmark import (
    OpenDataIndexBenchmarkError,
    _records_from_snapshot,
)

_DATASET_ID = "cn.csi300.index.daily"
_SNAPSHOT_PUBLICATION_ID = "b" * 32
_SNAPSHOT_SEQUENCE = 7
_START = date(2024, 1, 1)
_END = date(2024, 1, 5)


def _snapshot() -> dict[str, Any]:
    return {
        "dataset_id": _DATASET_ID,
        "publication_id": _SNAPSHOT_PUBLICATION_ID,
        "sequence": _SNAPSHOT_SEQUENCE,
    }


def _record(
    business_date: str,
    *,
    publication_id: str,
    publication_sequence: int,
) -> dict[str, Any]:
    symbol = "000300.SH"
    return {
        "dataset_id": _DATASET_ID,
        "business_key": json.dumps([symbol, business_date], separators=(",", ":")),
        "revision": 1,
        "publication_id": publication_id,
        "publication_sequence": publication_sequence,
        "business_date": business_date,
        "event_at": None,
        "observed_at": "2024-01-02T08:00:00+08:00",
        "source_published_at": "2024-01-02T08:00:00+08:00",
        "available_at": "2024-01-02T08:00:01+08:00",
        "payload": {
            "symbol": symbol,
            "trade_date": business_date,
            "open": 3500.0,
            "high": 3550.0,
            "low": 3490.0,
            "close": 3510.0,
            "volume": 100.0,
        },
        "record_hash": "d" * 64,
    }


def _validate(records: tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    return _records_from_snapshot(
        records,
        snapshot=_snapshot(),
        provider_symbol="000300.SH",
        start=_START,
        end=_END,
    )


def test_rejects_different_publication_ids_for_one_sequence() -> None:
    records = (
        _record("2024-01-01", publication_id="c" * 32, publication_sequence=4),
        _record("2024-01-02", publication_id="e" * 32, publication_sequence=4),
    )

    with pytest.raises(OpenDataIndexBenchmarkError) as exc_info:
        _validate(records)

    assert exc_info.value.code == "opendata_record_identity_invalid"


def test_rejects_one_historical_publication_id_reused_across_sequences_five_and_six() -> None:
    records = (
        _record("2024-01-01", publication_id="c" * 32, publication_sequence=5),
        _record("2024-01-02", publication_id="c" * 32, publication_sequence=6),
    )

    with pytest.raises(OpenDataIndexBenchmarkError) as exc_info:
        _validate(records)

    assert exc_info.value.code == "opendata_record_identity_invalid"


def test_rejects_another_publication_id_at_the_pinned_snapshot_sequence() -> None:
    records = (_record("2024-01-01", publication_id="c" * 32, publication_sequence=7),)

    with pytest.raises(OpenDataIndexBenchmarkError) as exc_info:
        _validate(records)

    assert exc_info.value.code == "opendata_record_identity_invalid"


def test_rejects_one_publication_id_for_different_sequences_including_snapshot_pin() -> None:
    records = (
        _record(
            "2024-01-01",
            publication_id=_SNAPSHOT_PUBLICATION_ID,
            publication_sequence=4,
        ),
    )

    with pytest.raises(OpenDataIndexBenchmarkError) as exc_info:
        _validate(records)

    assert exc_info.value.code == "opendata_record_identity_invalid"


def test_accepts_multiple_rows_from_one_older_publication_and_the_pinned_current_one() -> None:
    records = (
        _record("2024-01-01", publication_id="c" * 32, publication_sequence=4),
        _record("2024-01-02", publication_id="c" * 32, publication_sequence=4),
        _record(
            "2024-01-03",
            publication_id=_SNAPSHOT_PUBLICATION_ID,
            publication_sequence=_SNAPSHOT_SEQUENCE,
        ),
    )

    result = _validate(records)

    assert [item["date"] for item in result] == ["2024-01-01", "2024-01-02", "2024-01-03"]
