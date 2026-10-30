"""Mock-only contract tests for pinned source-native Sina LRB snapshots."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

import httpx
import pytest

from app.services.market_data.opendata_credentials import OpendataCredentials
from app.services.stock_analysis import opendata_sina_lrb_snapshot as snapshot_reader_module
from app.services.stock_analysis.opendata_sina_lrb_snapshot import (
    OpenDataSinaLrbSnapshotError,
    OpenDataSinaLrbSnapshotReader,
)

_API_KEY = "mock-sina-lrb-snapshot-key"
_BASE_URL = "https://opendata.example.test"
_INSTRUMENT_ID = "600519.SH"
_PUBLICATION_ID = "a" * 32
_CAPTURE_ID = "b" * 64
_SNAPSHOT_ID = "c" * 32
_SOURCE = {"source": "sina", "source_id": "sina-lrb"}
_BUSINESS_FIELDS = [
    "instrument_id",
    "capture_id",
    "statement_code",
    "record_kind",
    "record_key",
]
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
    "business_key_fields": _BUSINESS_FIELDS,
    "identity_key_encoding": "canonical-json-array-v1",
    "revision": "latest non-deleted revision per business_key at the pinned publication sequence",
    "ordering_fields": _BUSINESS_FIELDS,
    "storage_order": _STORAGE_ORDER,
    "temporal_semantics": "none",
    "time_field": None,
    "temporal_fields": _TEMPORAL_FIELDS,
}
_SCHEMA_FIELDS = [
    {"name": name, "data_type": data_type, "nullable": nullable}
    for name, data_type, nullable in (
        ("instrument_id", "string", False),
        ("capture_id", "string", False),
        ("statement_code", "string", False),
        ("source_paper_code", "string", False),
        ("record_kind", "string", False),
        ("record_key", "string", False),
        ("response_encoding", "string", False),
        ("retrieved_at_utc", "datetime", False),
        ("response_sha256", "string", False),
        ("report_list_key", "string", True),
        ("report_list_ordinal", "integer", True),
        ("report_date_ordinal", "integer", True),
        ("response_context", "object", True),
        ("report_date_entry", "object", True),
        ("report_list_entry", "object", True),
    )
]
_CONTRACT_SHA256 = "a8aec8a825b481a4dbf17845df36ef6c15a8caa52929120c563270683eecf459"
_GOLDEN_RECORD_SHA256 = "d6f8a3e794bccc18844feb2d4fa3b566607e8b0b41a66fb7a80ddf6b2e261e87"
_RETRIEVED_AT = "2026-10-30T01:00:00.000000Z"
_OBSERVED_AT = "2026-10-30T01:00:00+00:00"


def _snapshot(*, record_count: int, **changes: Any) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "snapshot_id": _SNAPSHOT_ID,
        "dataset_id": "sina_lrb_report_observations",
        "publication_id": _PUBLICATION_ID,
        "sequence": 1,
        "schema_version": "source-native-report-v1",
        "semantic_version": "sina-lrb-source-native-v1",
        "source": _SOURCE,
        "schema": _SCHEMA_FIELDS,
        "quality": {"status": "unknown", "report_id": None, "issue_count": 0},
        "field_units": {
            "report_list_ordinal": "source_ordinal",
            "report_date_ordinal": "source_ordinal",
        },
        "field_currencies": {},
        "field_adjustments": {},
        "currency": None,
        "adjustment_basis": "not_applicable",
        "asset_class": "equity",
        "frequency": "irregular",
        "record_kind": "table",
        "business_key_fields": _BUSINESS_FIELDS,
        "ordering_fields": _BUSINESS_FIELDS,
        "storage_order": _STORAGE_ORDER,
        "identity_key_encoding": "canonical-json-array-v1",
        "filter_fields": ["instrument_id", "capture_id"],
        "time_field": None,
        "temporal_semantics": "none",
        "timezone": "UTC",
        "pit_policy": "unsupported",
        "source_available_at_field": None,
        "calendar_id": None,
        "contract_sha256": _CONTRACT_SHA256,
        "window": {"start": None, "end": None, "end_exclusive": True},
        "page_size": 30,
        "as_of": _OBSERVED_AT,
        "created_at": _OBSERVED_AT,
        "expires_at": "2026-10-30T01:10:00+00:00",
        "record_count": record_count,
        "selection_sha256": "e" * 64,
        "content_sha256": "f" * 64,
        "identity_semantics": _IDENTITY_SEMANTICS,
        "selection": {"instrument_id": _INSTRUMENT_ID, "capture_id": _CAPTURE_ID},
    }
    snapshot.update(changes)
    return snapshot


def _node_table(*, context: bool = False, marker: str = "opaque-source-value") -> dict[str, Any]:
    if context:
        return {
            "encoding": "sina-lrb-node-table-v1",
            "root_id": 0,
            "nodes": [
                {"id": 0, "kind": "object", "fields": [["report_date", 1], ["report_list", 2]]},
                {"id": 1, "kind": "reference", "name": "report_date"},
                {"id": 2, "kind": "reference", "name": "report_list"},
            ],
        }
    return {
        "encoding": "sina-lrb-node-table-v1",
        "root_id": 0,
        "nodes": [
            {"id": 0, "kind": "object", "fields": [["source_member", 1]]},
            {"id": 1, "kind": "string", "value": marker},
        ],
    }


def _payload(record_kind: str, record_key: str, ordinal: int | None) -> dict[str, Any]:
    common: dict[str, Any] = {
        "instrument_id": _INSTRUMENT_ID,
        "capture_id": _CAPTURE_ID,
        "statement_code": "lrb",
        "source_paper_code": "sh600519",
        "record_kind": record_kind,
        "record_key": record_key,
        "response_encoding": "sina-lrb-node-table-v1",
        "retrieved_at_utc": _RETRIEVED_AT,
        "response_sha256": "9" * 64,
        "report_list_key": None,
        "report_list_ordinal": None,
        "report_date_ordinal": None,
        "response_context": None,
        "report_date_entry": None,
        "report_list_entry": None,
    }
    if record_kind == "context":
        common["response_context"] = _node_table(context=True)
    else:
        assert ordinal is not None
        common.update(
            {
                "report_list_key": record_key,
                "report_list_ordinal": ordinal,
                "report_date_ordinal": ordinal,
                "report_date_entry": _node_table(marker=f"date-node-{ordinal}"),
                "report_list_entry": _node_table(marker=f"report-node-{ordinal}"),
            }
        )
    return common


def _record(record_kind: str, record_key: str, ordinal: int | None) -> dict[str, Any]:
    payload = _payload(record_kind, record_key, ordinal)
    business_key = json.dumps(
        [_INSTRUMENT_ID, _CAPTURE_ID, "lrb", record_kind, record_key],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    record = {
        "dataset_id": "sina_lrb_report_observations",
        "business_key": business_key,
        "revision": 1,
        "publication_id": _PUBLICATION_ID,
        "publication_sequence": 1,
        "business_date": None,
        "event_at": None,
        "observed_at": _OBSERVED_AT,
        "source_published_at": None,
        "available_at": None,
        "payload": payload,
        "record_hash": "",
    }
    canonical = {
        "business_key": business_key,
        "business_date": None,
        "event_at": None,
        "observed_at": datetime.fromisoformat(_OBSERVED_AT)
        .astimezone(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z"),
        "source_published_at": None,
        "available_at": None,
        "payload": payload,
        "selection": {"instrument_id": _INSTRUMENT_ID, "capture_id": _CAPTURE_ID},
    }
    record["record_hash"] = hashlib.sha256(
        json.dumps(
            canonical,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    return record


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
            "ordering_fields": _BUSINESS_FIELDS,
            "storage_order": _STORAGE_ORDER,
            "identity_key_encoding": "canonical-json-array-v1",
        },
    }


def _reader(handler: Callable[[httpx.Request], httpx.Response]) -> OpenDataSinaLrbSnapshotReader:
    return OpenDataSinaLrbSnapshotReader(
        OpendataCredentials(_API_KEY, base_url=_BASE_URL),
        transport=httpx.MockTransport(handler),
        allowed_hosts="opendata.example.test",
    )


def _multi_page_handler(
    requests: list[httpx.Request], *, bad_page: str | None = None
) -> Callable[[httpx.Request], httpx.Response]:
    rows = [_record("context", "context", None)] + [
        _record("report", f"report-{index:03d}", index) for index in range(30)
    ]
    rows.sort(key=lambda row: row["business_key"])
    snapshot = _snapshot(record_count=len(rows))

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["x-api-key"] == _API_KEY
        if request.method == "POST":
            assert request.url.path == "/api/v2/snapshots"
            body = json.loads(request.content)
            assert body == {
                "dataset_id": "sina_lrb_report_observations",
                "publication_id": _PUBLICATION_ID,
                "page_size": 30,
                "instrument_id": _INSTRUMENT_ID,
                "capture_id": _CAPTURE_ID,
            }
            return httpx.Response(201, json=snapshot)
        assert request.method == "GET"
        assert request.url.path == "/api/v2/datasets/sina_lrb_report_observations/records"
        assert request.url.params.get("snapshot_id") == _SNAPSHOT_ID
        if request.url.params.get("cursor") is None:
            first_page_rows = rows[:30]
            if bad_page == "payload_hash":
                first_page_rows[0]["payload"]["response_sha256"] = "7" * 64
            page = _page(snapshot, first_page_rows, next_cursor="opaque-next-page")
            if bad_page == "contract_hash":
                page["contract_sha256"] = "0" * 64
            return httpx.Response(200, json=page)
        assert request.url.params.get("cursor") == "opaque-next-page"
        second_page_rows = rows[30:]
        if bad_page == "duplicate":
            second_page_rows = [rows[29]]
        return httpx.Response(200, json=_page(snapshot, second_page_rows))

    return handle


@pytest.mark.asyncio
async def test_reader_reads_and_validates_complete_source_native_capture() -> None:
    requests: list[httpx.Request] = []
    reader = _reader(_multi_page_handler(requests))

    result = await reader.fetch_capture(
        instrument_id=_INSTRUMENT_ID,
        publication_id=_PUBLICATION_ID,
        capture_id=_CAPTURE_ID,
    )

    assert [request.method for request in requests] == ["POST", "GET", "GET"]
    assert result.page_count == 2
    assert len(result.records) == 31
    assert result.report_count == 30
    assert result.snapshot["selection"] == {
        "instrument_id": _INSTRUMENT_ID,
        "capture_id": _CAPTURE_ID,
    }
    assert result.records[0]["payload"]["record_kind"] == "context"
    assert result.records[1]["payload"]["report_list_entry"]["nodes"][1]["value"] == (
        "report-node-0"
    )
    assert result.completeness == "unknown"
    assert result.historical_as_of_status == "unavailable"
    assert result.eligible_for_decision_or_backtest is False
    assert result.record_hash_verification == "verified"
    assert result.selection_hash_verification == "unavailable_access_scope_not_returned"
    assert result.content_hash_verification == "unavailable_access_scope_not_returned"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("instrument_id", "publication_id", "capture_id", "expected_code"),
    [
        ("600519.BJ", _PUBLICATION_ID, _CAPTURE_ID, "instrument_id_invalid"),
        ("600519.SH", "bad", _CAPTURE_ID, "publication_id_invalid"),
        ("600519.SH", _PUBLICATION_ID, "bad", "capture_id_invalid"),
    ],
)
async def test_reader_rejects_noncanonical_or_unsupported_selector_before_http(
    instrument_id: str,
    publication_id: str,
    capture_id: str,
    expected_code: str,
) -> None:
    requests: list[httpx.Request] = []
    reader = _reader(_multi_page_handler(requests))

    with pytest.raises(OpenDataSinaLrbSnapshotError) as raised:
        await reader.fetch_capture(
            instrument_id=instrument_id,
            publication_id=publication_id,
            capture_id=capture_id,
        )

    assert raised.value.code == expected_code
    assert requests == []


@pytest.mark.asyncio
async def test_reader_rejects_page_contract_hash_drift_without_returning_partial_data() -> None:
    requests: list[httpx.Request] = []
    reader = _reader(_multi_page_handler(requests, bad_page="contract_hash"))

    with pytest.raises(OpenDataSinaLrbSnapshotError) as raised:
        await reader.fetch_capture(
            instrument_id=_INSTRUMENT_ID,
            publication_id=_PUBLICATION_ID,
            capture_id=_CAPTURE_ID,
        )

    assert raised.value.code == "snapshot_contract_hash_mismatch"
    assert [request.method for request in requests] == ["POST", "GET"]


@pytest.mark.asyncio
async def test_reader_rejects_duplicate_record_across_pages() -> None:
    requests: list[httpx.Request] = []
    reader = _reader(_multi_page_handler(requests, bad_page="duplicate"))

    with pytest.raises(OpenDataSinaLrbSnapshotError) as raised:
        await reader.fetch_capture(
            instrument_id=_INSTRUMENT_ID,
            publication_id=_PUBLICATION_ID,
            capture_id=_CAPTURE_ID,
        )

    assert raised.value.code == "duplicate_business_key"


@pytest.mark.asyncio
async def test_reader_recomputes_record_hash_and_rejects_tampered_payload() -> None:
    requests: list[httpx.Request] = []
    reader = _reader(_multi_page_handler(requests, bad_page="payload_hash"))

    with pytest.raises(OpenDataSinaLrbSnapshotError) as raised:
        await reader.fetch_capture(
            instrument_id=_INSTRUMENT_ID,
            publication_id=_PUBLICATION_ID,
            capture_id=_CAPTURE_ID,
        )

    assert raised.value.code == "record_hash_mismatch"
    assert [request.method for request in requests] == ["POST", "GET"]


def test_record_hash_matches_precomputed_unicode_decimal_golden_vector() -> None:
    record = _record("report", "golden-report", 0)
    record["payload"]["report_list_entry"] = {
        "encoding": "sina-lrb-node-table-v1",
        "root_id": 0,
        "nodes": [
            {
                "id": 0,
                "kind": "object",
                "fields": [["中文字段", 1], ["decimal", 2], ["整数", 3]],
            },
            {"id": 1, "kind": "string", "value": "营业收入"},
            {"id": 2, "kind": "decimal", "sign": 0, "digits": "123450", "exponent": -2},
            {"id": 3, "kind": "integer", "value": 2026},
        ],
    }
    # Precomputed independently from publication_store's canonical record JSON;
    # this pins Unicode, Decimal digits/exponent strings, and integer encoding.
    record["record_hash"] = _GOLDEN_RECORD_SHA256

    identity = snapshot_reader_module._validate_record(
        record,
        snapshot=_snapshot(record_count=1),
        instrument_id=_INSTRUMENT_ID,
        capture_id=_CAPTURE_ID,
    )

    assert identity == ("sh600519", "9" * 64, _RETRIEVED_AT)


@pytest.mark.asyncio
async def test_reader_rejects_page_limit_without_returning_partial_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []
    monkeypatch.setattr(snapshot_reader_module, "_MAX_PAGES", 1)
    reader = _reader(_multi_page_handler(requests))

    with pytest.raises(OpenDataSinaLrbSnapshotError) as raised:
        await reader.fetch_capture(
            instrument_id=_INSTRUMENT_ID,
            publication_id=_PUBLICATION_ID,
            capture_id=_CAPTURE_ID,
        )

    assert raised.value.code == "snapshot_page_limit_exceeded"
    assert [request.method for request in requests] == ["POST", "GET"]


@pytest.mark.asyncio
async def test_reader_rejects_oversized_response_before_json_parsing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            201,
            headers={"content-type": "application/json"},
            content=b'{"x":1}',
        )

    monkeypatch.setattr(snapshot_reader_module, "_MAX_RESPONSE_BYTES", 4)
    reader = _reader(handle)

    with pytest.raises(OpenDataSinaLrbSnapshotError) as raised:
        await reader.fetch_capture(
            instrument_id=_INSTRUMENT_ID,
            publication_id=_PUBLICATION_ID,
            capture_id=_CAPTURE_ID,
        )

    assert raised.value.code == "response_too_large"
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_reader_rejects_truncated_pagination_without_returning_partial_rows() -> None:
    requests: list[httpx.Request] = []
    rows = [_record("context", "context", None)] + [
        _record("report", f"report-{index:03d}", index) for index in range(30)
    ]
    rows.sort(key=lambda row: row["business_key"])
    snapshot = _snapshot(record_count=len(rows))

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(201, json=snapshot)
        return httpx.Response(200, json=_page(snapshot, rows[:30], next_cursor=None))

    reader = _reader(handle)
    with pytest.raises(OpenDataSinaLrbSnapshotError) as raised:
        await reader.fetch_capture(
            instrument_id=_INSTRUMENT_ID,
            publication_id=_PUBLICATION_ID,
            capture_id=_CAPTURE_ID,
        )

    assert raised.value.code == "snapshot_incomplete"
    assert [request.method for request in requests] == ["POST", "GET"]


@pytest.mark.parametrize(
    ("changes", "expected_code"),
    [
        ({"semantic_version": "sina-fzb-source-native-v1"}, "snapshot_contract_mismatch"),
        ({"source": {"source": "sina", "source_id": "sina-fzb"}}, "snapshot_contract_mismatch"),
        ({"pit_policy": "supported"}, "snapshot_contract_mismatch"),
        ({"contract_sha256": "0" * 64}, "snapshot_contract_hash_mismatch"),
        (
            {"selection": {"instrument_id": "000001.SZ", "capture_id": _CAPTURE_ID}},
            "snapshot_selection_mismatch",
        ),
        ({"record_count": 258}, "snapshot_row_limit_exceeded"),
    ],
)
def test_lrb_snapshot_validator_pins_contract_semantics_and_capture_scope(
    changes: dict[str, Any], expected_code: str
) -> None:
    snapshot = _snapshot(**{"record_count": 1, **changes})

    with pytest.raises(OpenDataSinaLrbSnapshotError) as raised:
        snapshot_reader_module._validate_snapshot(
            snapshot,
            instrument_id=_INSTRUMENT_ID,
            publication_id=_PUBLICATION_ID,
            capture_id=_CAPTURE_ID,
        )

    assert raised.value.code == expected_code


@pytest.mark.asyncio
async def test_reader_applies_exact_https_host_allowlist_before_request() -> None:
    requests: list[httpx.Request] = []
    reader = OpenDataSinaLrbSnapshotReader(
        OpendataCredentials(_API_KEY, base_url="https://other.example.test"),
        transport=httpx.MockTransport(_multi_page_handler(requests)),
        allowed_hosts="opendata.example.test",
    )

    with pytest.raises(OpenDataSinaLrbSnapshotError) as raised:
        await reader.fetch_capture(
            instrument_id=_INSTRUMENT_ID,
            publication_id=_PUBLICATION_ID,
            capture_id=_CAPTURE_ID,
        )

    assert raised.value.code == "base_url_host_not_allowed"
    assert requests == []


@pytest.mark.asyncio
async def test_reader_maps_auth_failure_without_exposing_server_body_or_retrying() -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            403,
            headers={"content-type": "application/json"},
            json={"detail": "private server diagnostic"},
        )

    reader = _reader(handle)
    with pytest.raises(OpenDataSinaLrbSnapshotError) as raised:
        await reader.fetch_capture(
            instrument_id=_INSTRUMENT_ID,
            publication_id=_PUBLICATION_ID,
            capture_id=_CAPTURE_ID,
        )

    assert raised.value.code == "http_403_forbidden"
    assert str(raised.value) == "http_403_forbidden"
    assert raised.value.status_code == 403
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_reader_does_not_follow_redirects() -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(307, headers={"location": "https://elsewhere.example.test"})

    reader = _reader(handle)
    with pytest.raises(OpenDataSinaLrbSnapshotError) as raised:
        await reader.fetch_capture(
            instrument_id=_INSTRUMENT_ID,
            publication_id=_PUBLICATION_ID,
            capture_id=_CAPTURE_ID,
        )

    assert raised.value.status_code == 307
    assert len(requests) == 1


@pytest.mark.parametrize(
    "table",
    [
        {"encoding": "wrong", "root_id": 0, "nodes": [{"id": 0, "kind": "null"}]},
        {
            "encoding": "sina-lrb-node-table-v1",
            "root_id": 0,
            "nodes": [{"id": 0, "kind": "object", "fields": [["x", 1]]}],
        },
        {
            "encoding": "sina-lrb-node-table-v1",
            "root_id": 0,
            "nodes": [
                {"id": 0, "kind": "object", "fields": [["x", 0]]},
            ],
        },
    ],
)
def test_node_table_structure_is_checked_without_interpreting_values(
    table: dict[str, Any],
) -> None:
    with pytest.raises(OpenDataSinaLrbSnapshotError) as raised:
        snapshot_reader_module._validate_node_table(table, context=False)

    assert raised.value.code == "record_payload_invalid"


@pytest.mark.asyncio
async def test_reader_rejects_empty_credentials_before_http() -> None:
    requests: list[httpx.Request] = []
    reader = OpenDataSinaLrbSnapshotReader(
        None, transport=httpx.MockTransport(_multi_page_handler(requests))
    )

    with pytest.raises(OpenDataSinaLrbSnapshotError) as raised:
        await reader.fetch_capture(
            instrument_id=_INSTRUMENT_ID,
            publication_id=_PUBLICATION_ID,
            capture_id=_CAPTURE_ID,
        )

    assert raised.value.code == "credential_missing"
    assert requests == []
