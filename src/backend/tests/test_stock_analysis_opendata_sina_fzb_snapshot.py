"""Mock-only contract tests for pinned source-native Sina FZB snapshots."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.services.market_data.opendata_credentials import OpendataCredentials
from app.services.stock_analysis import opendata_sina_fzb_snapshot as snapshot_reader_module
from app.services.stock_analysis.opendata_sina_fzb_snapshot import (
    OpenDataSinaFzbSnapshotError,
    OpenDataSinaFzbSnapshotReader,
)

_API_KEY = "mock-sina-snapshot-key"
_BASE_URL = "https://opendata.example.test"
_INSTRUMENT_ID = "600519.SH"
_PUBLICATION_ID = "a" * 32
_CAPTURE_ID = "b" * 64
_SNAPSHOT_ID = "c" * 32
_ORDERING_FIELDS = ["instrument_id", "capture_id", "statement_code", "report_period"]
_STORAGE_ORDER = [
    {"field": "business_date", "direction": "asc", "nulls": "last", "comparison": "native"},
    {"field": "business_key", "direction": "asc", "comparison": "binary_lexicographic"},
]
_TEMPORAL_FIELDS = {
    "business_date": "null for atemporal table records; not a historical business date",
    "observed_at": "source observation time",
    "source_published_at": "source publication time",
    "available_at": "platform availability time",
    "event_at": "source event time",
}
_IDENTITY_SEMANTICS = {
    "version": 1,
    "business_key_fields": _ORDERING_FIELDS,
    "identity_key_encoding": "canonical-json-array-v1",
    "revision": "latest non-deleted revision per business_key at the pinned publication sequence",
    "ordering_fields": _ORDERING_FIELDS,
    "storage_order": _STORAGE_ORDER,
    "temporal_semantics": "none",
    "time_field": None,
    "temporal_fields": _TEMPORAL_FIELDS,
}


def _snapshot(
    *,
    record_count: int,
    **changes: Any,
) -> dict[str, Any]:
    fields = (
        ("instrument_id", "string"),
        ("capture_id", "string"),
        ("statement_code", "string"),
        ("report_period", "date"),
        ("source_paper_code", "string"),
        ("published_on", "date"),
        ("publication_precision", "string"),
        ("source_update_epoch_seconds", "integer"),
        ("source_updated_at", "datetime"),
        ("source_updated_at_timezone", "string"),
        ("retrieved_at_utc", "datetime"),
        ("currency", "string"),
        ("period_metadata", "object"),
        ("report_metadata", "object"),
        ("entries", "array"),
    )
    result: dict[str, Any] = {
        "snapshot_id": _SNAPSHOT_ID,
        "dataset_id": "sina_fzb_report_observations",
        "publication_id": _PUBLICATION_ID,
        "sequence": 1,
        "schema_version": "source-native-report-v1",
        "semantic_version": "sina-fzb-source-native-v1",
        "source": {"source": "sina", "source_id": "sina-fzb"},
        "schema": [
            {"name": name, "data_type": data_type, "nullable": False} for name, data_type in fields
        ],
        "quality": {"status": "unknown", "report_id": None, "issue_count": 0},
        "field_units": {"source_update_epoch_seconds": "unix_seconds"},
        "field_currencies": {},
        "field_adjustments": {},
        "currency": None,
        "adjustment_basis": "not_applicable",
        "asset_class": "equity",
        "frequency": "irregular",
        "record_kind": "table",
        "business_key_fields": _ORDERING_FIELDS,
        "ordering_fields": _ORDERING_FIELDS,
        "storage_order": _STORAGE_ORDER,
        "identity_key_encoding": "canonical-json-array-v1",
        "filter_fields": ["instrument_id", "capture_id"],
        "time_field": None,
        "temporal_semantics": "none",
        "timezone": "UTC",
        "pit_policy": "unsupported",
        "source_available_at_field": None,
        "calendar_id": None,
        "contract_sha256": "d" * 64,
        "window": {"start": None, "end": None, "end_exclusive": True},
        "page_size": 30,
        "as_of": "2026-10-30T01:00:00+00:00",
        "created_at": "2026-10-30T01:00:00+00:00",
        "expires_at": "2026-10-30T01:10:00+00:00",
        "record_count": record_count,
        "selection_sha256": "e" * 64,
        "content_sha256": "f" * 64,
        "identity_semantics": _IDENTITY_SEMANTICS,
        "selection": {"instrument_id": _INSTRUMENT_ID, "capture_id": _CAPTURE_ID},
    }
    result.update(changes)
    return result


def _payload(report_period: str) -> dict[str, Any]:
    return {
        "instrument_id": _INSTRUMENT_ID,
        "capture_id": _CAPTURE_ID,
        "statement_code": "fzb",
        "report_period": report_period,
        "source_paper_code": "sh600519",
        "published_on": "2025-04-30",
        "publication_precision": "date",
        "source_update_epoch_seconds": 1_745_971_200,
        "source_updated_at": "2025-04-30T08:00:00+08:00",
        "source_updated_at_timezone": "Asia/Shanghai",
        "retrieved_at_utc": "2026-10-30T01:00:00.000000Z",
        "currency": "CNY",
        "period_metadata": {"year": 2024, "quarter": 4},
        "report_metadata": {"source_marker": "fixture"},
        "entries": [
            {
                "kind": "item",
                "source_item_id": "total_assets",
                "source_title": "资产总计",
                "source_ordinals": [0],
                "raw_value": "0.00",
                "value_state": "present",
                "source_metadata": {"source_value": "0.00"},
            },
            {
                "kind": "item",
                "source_item_id": "empty_item",
                "source_title": "源空值",
                "source_ordinals": [1],
                "raw_value": "",
                "value_state": "empty",
                "source_metadata": {},
            },
            {
                "kind": "item",
                "source_item_id": "null_item",
                "source_title": "源空值标记",
                "source_ordinals": [2],
                "raw_value": None,
                "value_state": "null",
                "source_metadata": {},
            },
            {
                "kind": "group_marker",
                "source_ordinals": [3],
                "source_group_no": 1,
                "source_title": "流动资产",
                "raw_item_field": "",
                "raw_item_value": "",
                "source_metadata": {"item_source": "fzb"},
            },
        ],
    }


def _row(report_period: str) -> dict[str, Any]:
    payload = _payload(report_period)
    business_key = json.dumps(
        [_INSTRUMENT_ID, _CAPTURE_ID, "fzb", report_period],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return {
        "dataset_id": "sina_fzb_report_observations",
        "business_key": business_key,
        "revision": 1,
        "publication_id": _PUBLICATION_ID,
        "publication_sequence": 1,
        "business_date": None,
        "event_at": None,
        "observed_at": "2026-10-30T01:00:00+00:00",
        "source_published_at": None,
        "available_at": None,
        "payload": payload,
        "record_hash": "9" * 64,
    }


def _page(
    snapshot: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    next_cursor: str | None = None,
) -> dict[str, Any]:
    return {
        **snapshot,
        "rows": rows,
        "count": len(rows),
        "next_cursor": next_cursor,
        "has_more": next_cursor is not None,
        "meta": {
            "snapshot": snapshot,
            "ordering_fields": _ORDERING_FIELDS,
            "storage_order": _STORAGE_ORDER,
            "identity_key_encoding": "canonical-json-array-v1",
        },
    }


def _reader(handler: Callable[[httpx.Request], httpx.Response]) -> OpenDataSinaFzbSnapshotReader:
    return OpenDataSinaFzbSnapshotReader(
        OpendataCredentials(_API_KEY, base_url=_BASE_URL),
        transport=httpx.MockTransport(handler),
        allowed_hosts={"opendata.example.test"},
    )


@pytest.mark.asyncio
async def test_reader_pins_publication_and_preserves_all_source_native_values() -> None:
    first = _row("2024-06-30")
    second = _row("2024-09-30")
    snapshot = _snapshot(record_count=2)
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["X-API-Key"] == _API_KEY
        assert request.headers["Accept"] == "application/json"
        assert _API_KEY not in str(request.url)
        if request.method == "POST":
            assert request.url.path == "/api/v2/snapshots"
            assert json.loads(request.content) == {
                "dataset_id": "sina_fzb_report_observations",
                "publication_id": _PUBLICATION_ID,
                "page_size": 30,
                "instrument_id": _INSTRUMENT_ID,
                "capture_id": _CAPTURE_ID,
            }
            assert "start_date" not in json.loads(request.content)
            return httpx.Response(201, json=snapshot)
        assert request.url.path == "/api/v2/datasets/sina_fzb_report_observations/records"
        assert request.url.params["snapshot_id"] == _SNAPSHOT_ID
        if "cursor" not in request.url.params:
            return httpx.Response(200, json=_page(snapshot, [first], next_cursor="next-page"))
        assert request.url.params["cursor"] == "next-page"
        return httpx.Response(200, json=_page(snapshot, [second]))

    result = await _reader(handler).fetch_capture(
        instrument_id=_INSTRUMENT_ID,
        publication_id=_PUBLICATION_ID,
        capture_id=_CAPTURE_ID,
    )

    assert [(request.method, request.url.path) for request in requests] == [
        ("POST", "/api/v2/snapshots"),
        ("GET", "/api/v2/datasets/sina_fzb_report_observations/records"),
        ("GET", "/api/v2/datasets/sina_fzb_report_observations/records"),
    ]
    assert result.page_count == 2
    assert result.snapshot["publication_id"] == _PUBLICATION_ID
    assert result.records[0]["payload"]["entries"][0]["raw_value"] == "0.00"
    assert result.records[0]["payload"]["entries"][1]["value_state"] == "empty"
    assert result.records[0]["payload"]["entries"][2]["value_state"] == "null"
    assert result.records[0]["payload"]["entries"][3]["kind"] == "group_marker"
    assert result.records[0]["payload"]["source_updated_at"] == "2025-04-30T08:00:00+08:00"
    assert result.records[0]["payload"]["report_period"] == "2024-06-30"
    assert result.completeness == "unknown"
    assert result.historical_as_of_status == "unavailable"
    assert result.eligible_for_decision_or_backtest is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("instrument_id", "publication_id", "capture_id", "expected_code"),
    [
        ("920422.BJ", _PUBLICATION_ID, _CAPTURE_ID, "instrument_id_invalid"),
        ("600519.SH", "not-a-publication", _CAPTURE_ID, "publication_id_invalid"),
        ("600519.SH", _PUBLICATION_ID, "bad-capture", "capture_id_invalid"),
    ],
)
async def test_reader_rejects_invalid_identity_before_network(
    instrument_id: str,
    publication_id: str,
    capture_id: str,
    expected_code: str,
) -> None:
    reader = _reader(lambda _request: pytest.fail("invalid inputs must not use transport"))
    with pytest.raises(OpenDataSinaFzbSnapshotError) as raised:
        await reader.fetch_capture(
            instrument_id=instrument_id,
            publication_id=publication_id,
            capture_id=capture_id,
        )
    assert raised.value.code == expected_code


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"dataset_id": "equity.other"},
        {"publication_id": "1" * 32},
        {"source": {"source": "other", "source_id": "sina-fzb"}},
        {"schema_version": "source-native-report-v2"},
        {"semantic_version": "changed"},
        {"selection": {"instrument_id": "600001.SH", "capture_id": _CAPTURE_ID}},
        {"window": {"start": "2024-01-01", "end": None, "end_exclusive": True}},
        {"pit_policy": "supported"},
    ],
)
async def test_reader_rejects_snapshot_contract_or_scope_drift(changes: dict[str, Any]) -> None:
    altered = _snapshot(record_count=0, **changes)

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        return httpx.Response(201, json=altered)

    with pytest.raises(OpenDataSinaFzbSnapshotError):
        await _reader(handler).fetch_capture(
            instrument_id=_INSTRUMENT_ID,
            publication_id=_PUBLICATION_ID,
            capture_id=_CAPTURE_ID,
        )


@pytest.mark.asyncio
async def test_reader_returns_no_partial_records_when_later_page_changes_snapshot() -> None:
    snapshot = _snapshot(record_count=2)
    changed = dict(snapshot)
    changed["content_sha256"] = "1" * 64
    requests = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        if requests == 1:
            return httpx.Response(201, json=snapshot)
        if requests == 2:
            return httpx.Response(200, json=_page(snapshot, [_row("2024-06-30")], next_cursor="p2"))
        return httpx.Response(200, json=_page(changed, [_row("2024-09-30")]))

    with pytest.raises(OpenDataSinaFzbSnapshotError) as raised:
        await _reader(handler).fetch_capture(
            instrument_id=_INSTRUMENT_ID,
            publication_id=_PUBLICATION_ID,
            capture_id=_CAPTURE_ID,
        )
    assert raised.value.code == "records_snapshot_mismatch"
    assert requests == 3


@pytest.mark.asyncio
async def test_reader_requires_observed_at_to_match_source_retrieval_instant() -> None:
    snapshot = _snapshot(record_count=1)
    row = _row("2024-06-30")
    row["observed_at"] = "2026-10-30T01:00:01+00:00"

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(201, json=snapshot)
        return httpx.Response(200, json=_page(snapshot, [row]))

    with pytest.raises(OpenDataSinaFzbSnapshotError) as raised:
        await _reader(handler).fetch_capture(
            instrument_id=_INSTRUMENT_ID,
            publication_id=_PUBLICATION_ID,
            capture_id=_CAPTURE_ID,
        )
    assert raised.value.code == "record_observation_time_mismatch"


@pytest.mark.asyncio
async def test_reader_enforces_opendata_business_key_length_limit() -> None:
    snapshot = _snapshot(record_count=1)
    row = _row("2024-06-30")
    row["business_key"] = "x" * 513

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(201, json=snapshot)
        return httpx.Response(200, json=_page(snapshot, [row]))

    with pytest.raises(OpenDataSinaFzbSnapshotError) as raised:
        await _reader(handler).fetch_capture(
            instrument_id=_INSTRUMENT_ID,
            publication_id=_PUBLICATION_ID,
            capture_id=_CAPTURE_ID,
        )
    assert raised.value.code == "record_business_key_invalid"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "expected_code"),
    [
        (401, "http_401_unauthorized"),
        (403, "http_403_forbidden"),
        (404, "http_404_not_found"),
        (410, "http_410_snapshot_expired"),
        (413, "http_413_too_large"),
        (422, "http_422_invalid_request"),
        (429, "http_429_rate_limited"),
        (503, "http_server_error"),
    ],
)
async def test_http_errors_are_stable_and_never_expose_response_body(
    status_code: int,
    expected_code: str,
) -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"message": _API_KEY, "private": "body"})

    with pytest.raises(OpenDataSinaFzbSnapshotError) as raised:
        await _reader(handler).fetch_capture(
            instrument_id=_INSTRUMENT_ID,
            publication_id=_PUBLICATION_ID,
            capture_id=_CAPTURE_ID,
        )
    assert raised.value.code == expected_code
    assert _API_KEY not in str(raised.value)
    assert "private" not in str(raised.value)


@pytest.mark.asyncio
async def test_reader_never_follows_redirect_to_another_host() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(302, headers={"Location": "https://attacker.example.test/collect"})

    with pytest.raises(OpenDataSinaFzbSnapshotError) as raised:
        await _reader(handler).fetch_capture(
            instrument_id=_INSTRUMENT_ID,
            publication_id=_PUBLICATION_ID,
            capture_id=_CAPTURE_ID,
        )
    assert raised.value.status_code == 302
    assert len(requests) == 1
    assert requests[0].headers["X-API-Key"] == _API_KEY


@pytest.mark.asyncio
async def test_reader_rejects_duplicate_json_keys_and_nonfinite_numbers() -> None:
    valid = json.dumps(_snapshot(record_count=0), separators=(",", ":"))
    duplicate_key_body = valid[:-1] + ',"dataset_id":"sina_fzb_report_observations"}'

    async def duplicate_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            201, content=duplicate_key_body, headers={"content-type": "application/json"}
        )

    with pytest.raises(OpenDataSinaFzbSnapshotError) as duplicate_error:
        await _reader(duplicate_handler).fetch_capture(
            instrument_id=_INSTRUMENT_ID,
            publication_id=_PUBLICATION_ID,
            capture_id=_CAPTURE_ID,
        )
    assert duplicate_error.value.code == "response_json_invalid"

    nonfinite_body = valid[:-1] + ',"unsafe":NaN}'

    async def nonfinite_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            201, content=nonfinite_body, headers={"content-type": "application/json"}
        )

    with pytest.raises(OpenDataSinaFzbSnapshotError) as nonfinite_error:
        await _reader(nonfinite_handler).fetch_capture(
            instrument_id=_INSTRUMENT_ID,
            publication_id=_PUBLICATION_ID,
            capture_id=_CAPTURE_ID,
        )
    assert nonfinite_error.value.code == "response_json_invalid"


@pytest.mark.asyncio
async def test_reader_rejects_cursor_cycles_and_wrong_row_count() -> None:
    snapshot = _snapshot(record_count=2)

    async def cursor_handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(201, json=snapshot)
        report_period = "2024-09-30" if "cursor" in request.url.params else "2024-06-30"
        return httpx.Response(
            200,
            json=_page(snapshot, [_row(report_period)], next_cursor="again"),
        )

    with pytest.raises(OpenDataSinaFzbSnapshotError) as cursor_error:
        await _reader(cursor_handler).fetch_capture(
            instrument_id=_INSTRUMENT_ID,
            publication_id=_PUBLICATION_ID,
            capture_id=_CAPTURE_ID,
        )
    assert cursor_error.value.code == "snapshot_cursor_repeated"

    async def count_handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(201, json=snapshot)
        return httpx.Response(200, json=_page(snapshot, [_row("2024-06-30")]))

    with pytest.raises(OpenDataSinaFzbSnapshotError) as count_error:
        await _reader(count_handler).fetch_capture(
            instrument_id=_INSTRUMENT_ID,
            publication_id=_PUBLICATION_ID,
            capture_id=_CAPTURE_ID,
        )
    assert count_error.value.code == "snapshot_incomplete"


@pytest.mark.asyncio
async def test_reader_rejects_duplicate_business_key_across_pages() -> None:
    snapshot = _snapshot(record_count=2)
    duplicate_row = _row("2024-06-30")

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(201, json=snapshot)
        if "cursor" not in request.url.params:
            return httpx.Response(
                200,
                json=_page(snapshot, [duplicate_row], next_cursor="page-2"),
            )
        return httpx.Response(200, json=_page(snapshot, [duplicate_row]))

    with pytest.raises(OpenDataSinaFzbSnapshotError) as raised:
        await _reader(handler).fetch_capture(
            instrument_id=_INSTRUMENT_ID,
            publication_id=_PUBLICATION_ID,
            capture_id=_CAPTURE_ID,
        )
    assert raised.value.code == "duplicate_business_key"


@pytest.mark.asyncio
async def test_total_response_budget_caps_each_streamed_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(snapshot_reader_module, "_MAX_TOTAL_RESPONSE_BYTES", 8_192)
    snapshot = _snapshot(record_count=0)

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(201, json=snapshot)
        return httpx.Response(
            200,
            content=b" " * 8_192,
            headers={"content-type": "application/json"},
        )

    with pytest.raises(OpenDataSinaFzbSnapshotError) as raised:
        await _reader(handler).fetch_capture(
            instrument_id=_INSTRUMENT_ID,
            publication_id=_PUBLICATION_ID,
            capture_id=_CAPTURE_ID,
        )
    assert raised.value.code == "response_too_large"


@pytest.mark.asyncio
async def test_reader_fails_closed_when_success_response_reflects_api_key() -> None:
    body = json.dumps(_snapshot(record_count=0), separators=(",", ":")) + _API_KEY

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, content=body, headers={"content-type": "application/json"})

    with pytest.raises(OpenDataSinaFzbSnapshotError) as raised:
        await _reader(handler).fetch_capture(
            instrument_id=_INSTRUMENT_ID,
            publication_id=_PUBLICATION_ID,
            capture_id=_CAPTURE_ID,
        )
    assert raised.value.code == "credential_reflected_in_response"
    assert _API_KEY not in str(raised.value)


@pytest.mark.asyncio
async def test_reader_rejects_api_key_reflected_with_json_unicode_escaping() -> None:
    body = (
        json.dumps(_snapshot(record_count=0), separators=(",", ":"))[:-1]
        + ',"message":"'
        + _API_KEY.replace("m", r"\u006d", 1)
        + '"}'
    )

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, content=body, headers={"content-type": "application/json"})

    with pytest.raises(OpenDataSinaFzbSnapshotError) as raised:
        await _reader(handler).fetch_capture(
            instrument_id=_INSTRUMENT_ID,
            publication_id=_PUBLICATION_ID,
            capture_id=_CAPTURE_ID,
        )
    assert raised.value.code == "credential_reflected_in_response"
    assert _API_KEY not in str(raised.value)
