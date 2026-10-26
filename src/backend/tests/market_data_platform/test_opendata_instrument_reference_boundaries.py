"""Public-client boundary tests for the offline OpenData reference adapter."""

from __future__ import annotations

import asyncio
import copy
import json
from collections.abc import AsyncIterator, Callable
from dataclasses import replace
from datetime import datetime

import httpx
import pytest

from tests.market_data_platform import test_opendata_instrument_reference as fixtures


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("dataset_id", "fixture bad id"),
        ("source_id", ""),
        ("api_key", "  "),
        ("api_key", " key-with-padding "),
        ("contract_sha256", "not-a-sha256-digest"),
        ("base_url", "https://catalog.example.test:not-a-port"),
        ("base_url", "https://catalog.example.test:0"),
    ],
)
def test_configuration_rejects_unusable_identity_and_credentials(field: str, value: str) -> None:
    with pytest.raises(fixtures.InstrumentReferenceError) as raised:
        replace(fixtures._config(), **{field: value})

    assert raised.value.code == "OPENDATA_REFERENCE_CONFIG_INVALID"
    if value:
        assert value not in str(raised.value)


@pytest.mark.parametrize(
    "invalid_dependency",
    ["config", "transport", "clock", "limits"],
)
def test_client_constructor_rejects_invalid_injected_dependencies(
    invalid_dependency: str,
) -> None:
    client_args: dict[str, object] = {invalid_dependency: object()}
    config = client_args.pop("config", fixtures._config())

    with pytest.raises(fixtures.InstrumentReferenceError) as raised:
        fixtures.InstrumentReferenceClient(config, **client_args)

    assert raised.value.code == "OPENDATA_REFERENCE_CONFIG_INVALID"


@pytest.mark.parametrize(
    "query",
    [
        {"search": " SYNTHETIC"},
        {"search": "SYNTHETIC\n"},
        {"search": "x" * 257},
        {"search": object()},
        {"effective_on": "2026-10-22"},
        {"effective_on": datetime(2026, 10, 22)},
    ],
)
async def test_invalid_queries_fail_before_transport(
    query: dict[str, object],
) -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return fixtures._response(fixtures._single_page())

    client = fixtures._client(httpx.MockTransport(handler))
    with pytest.raises(fixtures.InstrumentReferenceError) as raised:
        await client.list_options(**query)

    assert raised.value.code == "OPENDATA_REFERENCE_CONFIG_INVALID"
    assert requests == []


async def test_clock_failures_are_safe_configuration_errors() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return fixtures._response(fixtures._single_page())

    def broken_clock() -> datetime:
        raise RuntimeError("clock-secret")

    client = fixtures.InstrumentReferenceClient(
        fixtures._config(),
        transport=httpx.MockTransport(handler),
        clock=broken_clock,
        limits=fixtures._limits(),
    )
    with pytest.raises(fixtures.InstrumentReferenceError) as raised:
        await client.list_options()

    assert raised.value.code == "OPENDATA_REFERENCE_CONFIG_INVALID"
    assert "clock-secret" not in repr(raised.value)
    assert requests == []


@pytest.mark.parametrize("clock", [lambda: None, lambda: datetime(2026, 10, 22)])
async def test_clock_must_return_an_aware_datetime(clock: Callable[[], object]) -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return fixtures._response(fixtures._single_page())

    client = fixtures.InstrumentReferenceClient(
        fixtures._config(),
        transport=httpx.MockTransport(handler),
        clock=clock,
        limits=fixtures._limits(),
    )
    with pytest.raises(fixtures.InstrumentReferenceError) as raised:
        await client.list_options()

    assert raised.value.code == "OPENDATA_REFERENCE_CONFIG_INVALID"
    assert requests == []


@pytest.mark.parametrize(
    ("content_type", "content_length", "body", "expected_code"),
    [
        ("text/plain", None, b"{}", "OPENDATA_REFERENCE_PROTOCOL_INVALID"),
        ("application/json", "-1", b"{}", "OPENDATA_REFERENCE_PROTOCOL_INVALID"),
        ("application/json", "12x", b"{}", "OPENDATA_REFERENCE_PROTOCOL_INVALID"),
        ("application/json", None, b"", "OPENDATA_REFERENCE_PROTOCOL_INVALID"),
        ("application/json", None, b"\xff", "OPENDATA_REFERENCE_PROTOCOL_INVALID"),
        ("application/json", None, b"{", "OPENDATA_REFERENCE_PROTOCOL_INVALID"),
        ("application/json", None, b"NaN", "OPENDATA_REFERENCE_PROTOCOL_INVALID"),
        ("application/json", None, b"[]", "OPENDATA_REFERENCE_PROTOCOL_INVALID"),
    ],
)
async def test_rejects_invalid_wire_envelopes_without_echoing_them(
    content_type: str,
    content_length: str | None,
    body: bytes,
    expected_code: str,
) -> None:
    stream = fixtures._TrackingStream([body] if body else [])
    headers = {"content-type": content_type}
    if content_length is not None:
        headers["content-length"] = content_length
    response = httpx.Response(200, headers=headers, stream=stream)
    client = fixtures._client(httpx.MockTransport(lambda _: response))

    with pytest.raises(fixtures.InstrumentReferenceError) as raised:
        await client.list_options()

    assert raised.value.code == expected_code
    assert "NaN" not in repr(raised.value)
    assert stream.closed is True


async def test_json_suffix_media_type_and_bounded_option_search_are_supported() -> None:
    response_body = json.dumps(
        fixtures._single_page(), ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    response = fixtures._stream_response(
        response_body,
        headers={"content-type": "application/vnd.fixture+json; charset=utf-8"},
    )
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return response

    result = await fixtures._client(httpx.MockTransport(handler)).list_options(
        search="SYNTHETIC", limit=1
    )

    assert result["complete"] is True
    assert result["total"] == 1
    items = result["items"]
    assert isinstance(items, list)
    assert len(items) == 1
    assert len(requests) == 1
    assert requests[0].headers["accept-encoding"] == "identity"


async def test_response_stream_closes_but_injected_transport_remains_caller_owned() -> None:
    page = fixtures._single_page()
    body = json.dumps(page, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    streams: list[fixtures._TrackingStream] = []

    class CallerOwnedTransport(httpx.AsyncBaseTransport):
        def __init__(self) -> None:
            self.closed = False
            self.requests = 0

        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            self.requests += 1
            stream = fixtures._TrackingStream([body])
            streams.append(stream)
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                stream=stream,
            )

        async def aclose(self) -> None:
            self.closed = True

    transport = CallerOwnedTransport()
    client = fixtures.InstrumentReferenceClient(
        fixtures._config(),
        transport=transport,
        clock=fixtures._clock,
        limits=fixtures._limits(),
    )

    await client.list_options()
    await client.list_options()

    assert transport.requests == 2
    assert transport.closed is False
    assert [stream.closed for stream in streams] == [True, True]
    await transport.aclose()
    assert transport.closed is True


async def test_declared_oversize_is_rejected_before_reading_the_body() -> None:
    stream = fixtures._TrackingStream([b"private-body"])
    response = httpx.Response(
        200,
        headers={"content-type": "application/json", "content-length": "1024"},
        stream=stream,
    )
    client = fixtures._client(
        httpx.MockTransport(lambda _: response),
        limits=fixtures._limits(max_response_bytes=128, max_total_bytes=128),
    )

    with pytest.raises(fixtures.InstrumentReferenceError) as raised:
        await client.list_options()

    assert raised.value.code == "OPENDATA_REFERENCE_LIMIT_EXCEEDED"
    assert stream.read_count == 0
    assert stream.closed is True


async def test_exact_total_byte_budget_cannot_request_a_continuation_page() -> None:
    page = copy.deepcopy(fixtures._fixture()["pages"][0])
    encoded_size = len(
        json.dumps(page, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    )
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return fixtures._response(copy.deepcopy(page))

    client = fixtures._client(
        httpx.MockTransport(handler),
        limits=fixtures._limits(max_response_bytes=encoded_size, max_total_bytes=encoded_size),
    )
    with pytest.raises(fixtures.InstrumentReferenceError) as raised:
        await client.list_options()

    assert raised.value.code == "OPENDATA_REFERENCE_LIMIT_EXCEEDED"
    assert len(requests) == 1


async def test_snapshot_cannot_claim_more_pages_after_all_declared_rows_arrived() -> None:
    page = fixtures._single_page()
    page["has_more"] = True
    page["next_cursor"] = "cursor-after-complete-count"
    fixtures._sync_snapshot(page)
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return fixtures._response(page)

    with pytest.raises(fixtures.InstrumentReferenceError) as raised:
        await fixtures._client(httpx.MockTransport(handler)).list_options()

    assert raised.value.code == "OPENDATA_REFERENCE_PROTOCOL_INVALID"
    assert len(requests) == 1


async def test_tiny_total_deadline_fails_before_sending_a_request() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return fixtures._response(fixtures._single_page())

    client = fixtures._client(
        httpx.MockTransport(handler),
        limits=fixtures._limits(deadline_seconds=1e-10, request_timeout_seconds=0.5),
    )
    with pytest.raises(fixtures.InstrumentReferenceError) as raised:
        await client.list_options()

    assert raised.value.code == "OPENDATA_REFERENCE_LIMIT_EXCEEDED"
    assert requests == []


async def test_snapshot_expiry_is_checked_between_continuation_pages() -> None:
    requests: list[httpx.Request] = []
    clock_calls = 0
    expires_at = datetime.fromisoformat("2026-10-22T01:00:00+00:00")

    def clock() -> datetime:
        nonlocal clock_calls
        clock_calls += 1
        return fixtures._clock() if clock_calls <= 2 else expires_at

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return fixtures._response(copy.deepcopy(fixtures._fixture()["pages"][0]))

    client = fixtures.InstrumentReferenceClient(
        fixtures._config(),
        transport=httpx.MockTransport(handler),
        clock=clock,
        limits=fixtures._limits(),
    )
    with pytest.raises(fixtures.InstrumentReferenceError) as raised:
        await client.list_options()

    assert raised.value.code == "OPENDATA_REFERENCE_PROTOCOL_INVALID"
    assert len(requests) == 1


async def test_empty_snapshot_has_no_fabricated_registry_pins() -> None:
    page = copy.deepcopy(fixtures._fixture()["pages"][0])
    page["rows"] = []
    page["count"] = 0
    page["record_count"] = 0
    page["has_more"] = False
    page["next_cursor"] = None
    fixtures._sync_snapshot(page)

    result = await fixtures._client(
        httpx.MockTransport(lambda _: fixtures._response(page))
    ).list_options()

    assert result["complete"] is True
    assert result["total"] == 0
    assert result["items"] == []
    provenance = result["provenance"]
    assert isinstance(provenance, dict)
    assert provenance["registry_version"] is None
    assert provenance["profile_version"] is None


async def test_immediate_transport_timeout_is_an_unavailable_error() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        raise asyncio.TimeoutError("transport-timeout-detail")

    client = fixtures._client(
        httpx.MockTransport(handler),
        limits=fixtures._limits(deadline_seconds=5.0, request_timeout_seconds=2.0),
    )
    with pytest.raises(fixtures.InstrumentReferenceError) as raised:
        await client.list_options()

    assert raised.value.code == "OPENDATA_REFERENCE_UNAVAILABLE"
    assert "transport-timeout-detail" not in str(raised.value)
    assert len(requests) == 1


async def test_suspended_request_expiring_total_deadline_is_a_limit_error() -> None:
    requests: list[httpx.Request] = []
    never_release = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        await never_release.wait()
        return fixtures._response(fixtures._single_page())

    client = fixtures._client(
        httpx.MockTransport(handler),
        limits=fixtures._limits(deadline_seconds=0.05, request_timeout_seconds=0.2),
    )
    with pytest.raises(fixtures.InstrumentReferenceError) as raised:
        await asyncio.wait_for(client.list_options(), timeout=1.0)

    assert raised.value.code == "OPENDATA_REFERENCE_LIMIT_EXCEEDED"
    assert len(requests) == 1


async def test_transport_exception_is_redacted_and_never_retried() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        raise RuntimeError("credential-canary at https://internal.invalid/path")

    with pytest.raises(fixtures.InstrumentReferenceError) as raised:
        await fixtures._client(httpx.MockTransport(handler)).list_options()

    assert raised.value.code == "OPENDATA_REFERENCE_UNAVAILABLE"
    assert "credential-canary" not in repr(raised.value)
    assert "internal.invalid" not in str(raised.value)
    assert len(requests) == 1


async def test_response_stream_failure_is_redacted_and_closed() -> None:
    class FailingStream(httpx.AsyncByteStream):
        def __init__(self) -> None:
            self.closed = False

        async def __aiter__(self) -> AsyncIterator[bytes]:
            raise RuntimeError("private-stream-detail")
            yield b""

        async def aclose(self) -> None:
            self.closed = True

    stream = FailingStream()
    response = httpx.Response(
        200,
        headers={"content-type": "application/json"},
        stream=stream,
    )
    with pytest.raises(fixtures.InstrumentReferenceError) as raised:
        await fixtures._client(httpx.MockTransport(lambda _: response)).list_options()

    assert raised.value.code == "OPENDATA_REFERENCE_UNAVAILABLE"
    assert "private-stream-detail" not in repr(raised.value)
    assert stream.closed is True


async def test_surrogate_codepoint_in_json_is_rejected_during_canonical_validation() -> None:
    page = fixtures._single_page()
    page["source"]["source"] = "bad\ud800source"
    fixtures._sync_snapshot(page)
    body = json.dumps(page, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    response = fixtures._stream_response(body)

    with pytest.raises(fixtures.InstrumentReferenceError) as raised:
        await fixtures._client(httpx.MockTransport(lambda _: response)).list_options()

    assert raised.value.code == "OPENDATA_REFERENCE_PROTOCOL_INVALID"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source", {"source_id": "other.source", "source": "synthetic-fixture"}),
        ("quality", {"status": "failed", "report_id": "fixture-quality-1", "issue_count": 1}),
        ("as_of", "not-an-offset-datetime"),
        ("as_of", "2026-10-22T00:00:00"),
        ("as_of", 1),
        ("expires_at", "2026-10-22T00:00:30+00:00"),
        ("selection_sha256", "not-a-sha256-digest"),
        ("content_sha256", "not-a-sha256-digest"),
        ("contract_sha256", "f" * 64),
        ("snapshot_id", "bad snapshot id"),
        ("sequence", 0),
        ("page_size", 2),
        ("record_count", True),
        ("currency", "USD"),
        ("next_cursor", "terminal-page-has-no-cursor"),
    ],
)
async def test_rejects_untrusted_snapshot_metadata_before_returning_options(
    field: str, value: object
) -> None:
    page = fixtures._single_page()
    page[field] = value
    fixtures._sync_snapshot(page)

    with pytest.raises(fixtures.InstrumentReferenceError) as raised:
        await fixtures._client(
            httpx.MockTransport(lambda _: fixtures._response(page))
        ).list_options()

    assert raised.value.code == "OPENDATA_REFERENCE_PROTOCOL_INVALID"


@pytest.mark.parametrize("malformation", ["extra-field", "meta-type", "snapshot-type"])
async def test_snapshot_envelope_rejects_unknown_or_mistyped_metadata(
    malformation: str,
) -> None:
    page = fixtures._single_page()
    if malformation == "extra-field":
        page["untrusted"] = "unexpected"
    elif malformation == "meta-type":
        page["meta"] = []
    else:
        page["meta"]["snapshot"] = []

    with pytest.raises(fixtures.InstrumentReferenceError) as raised:
        await fixtures._client(
            httpx.MockTransport(lambda _: fixtures._response(page))
        ).list_options()

    assert raised.value.code == "OPENDATA_REFERENCE_PROTOCOL_INVALID"


async def test_source_metadata_must_include_nonblank_safe_source_name() -> None:
    page = fixtures._single_page()
    page["source"]["source"] = " "
    fixtures._sync_snapshot(page)

    with pytest.raises(fixtures.InstrumentReferenceError) as raised:
        await fixtures._client(
            httpx.MockTransport(lambda _: fixtures._response(page))
        ).list_options()

    assert raised.value.code == "OPENDATA_REFERENCE_PROTOCOL_INVALID"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("dataset_id", "another.dataset"),
        ("publication_sequence", True),
        ("revision", 0),
        ("event_at", "not-an-offset-datetime"),
        ("publication_id", "another-publication"),
    ],
)
async def test_rejects_row_identity_and_timestamp_inconsistencies(
    field: str, value: object
) -> None:
    page = fixtures._single_page()
    row = page["rows"][0]
    row[field] = value
    fixtures._rehash_row(row)

    with pytest.raises(fixtures.InstrumentReferenceError) as raised:
        await fixtures._client(
            httpx.MockTransport(lambda _: fixtures._response(page))
        ).list_options()

    assert raised.value.code == "OPENDATA_REFERENCE_PROTOCOL_INVALID"


@pytest.mark.parametrize("row_shape", ["non-object", "payload-not-object", "wrong-business-key"])
async def test_rows_must_have_the_declared_record_shape(row_shape: str) -> None:
    page = fixtures._single_page()
    row = page["rows"][0]
    if row_shape == "non-object":
        page["rows"] = [None]
    elif row_shape == "payload-not-object":
        row["payload"] = []
        fixtures._rehash_row(row)
    else:
        row["business_key"] = '["TEST-OTHER-ID"]'
        fixtures._rehash_row(row)

    with pytest.raises(fixtures.InstrumentReferenceError) as raised:
        await fixtures._client(
            httpx.MockTransport(lambda _: fixtures._response(page))
        ).list_options()

    assert raised.value.code == "OPENDATA_REFERENCE_PROTOCOL_INVALID"


async def test_business_keys_must_stay_in_canonical_binary_order() -> None:
    pages = copy.deepcopy(fixtures._fixture()["pages"])
    for page in pages:
        row = page["rows"][0]
        payload = row["payload"]
        payload["instrument_id"] = (
            "TEST_XSHG_A" if payload["instrument_id"] == "TEST_XSHE_B" else "TEST_XSHE_B"
        )
        row["business_key"] = json.dumps(
            [payload["instrument_id"]], ensure_ascii=False, separators=(",", ":")
        )
        fixtures._rehash_row(row)

    with pytest.raises(fixtures.InstrumentReferenceError) as raised:
        await fixtures._client(fixtures._pages_transport(pages)).list_options()

    assert raised.value.code == "OPENDATA_REFERENCE_PROTOCOL_INVALID"


async def test_malformed_row_hash_format_is_rejected_before_hash_comparison() -> None:
    page = fixtures._single_page()
    page["rows"][0]["record_hash"] = "not-a-sha256-digest"

    with pytest.raises(fixtures.InstrumentReferenceError) as raised:
        await fixtures._client(
            httpx.MockTransport(lambda _: fixtures._response(page))
        ).list_options()

    assert raised.value.code == "OPENDATA_REFERENCE_PROTOCOL_INVALID"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("status", "delisted"),
        ("status", "suspended"),
        ("status_as_of", "2026-13-22"),
        ("status_evidence_ref", "bad evidence ref"),
        ("start_boundary_unknown", False),
        ("start_evidence_ref", "TEST-204-START"),
        ("start_evidence_ref", "bad evidence ref"),
        ("known_start_date", "1991-01-01"),
        ("known_start_date", "1991-1-1"),
        ("delisted_on", "2026-10-20"),
        ("delisted_on", "not-a-date"),
        ("delist_evidence_ref", "bad evidence ref"),
    ],
)
async def test_rejects_lifecycle_claims_without_matching_evidence(
    field: str, value: object
) -> None:
    page = fixtures._single_page()
    row = page["rows"][0]
    row["payload"][field] = value
    fixtures._rehash_row(row)

    with pytest.raises(fixtures.InstrumentReferenceError) as raised:
        await fixtures._client(
            httpx.MockTransport(lambda _: fixtures._response(page))
        ).list_options()

    assert raised.value.code == "OPENDATA_REFERENCE_PROTOCOL_INVALID"


async def test_valid_delisted_lifecycle_is_preserved_without_inference() -> None:
    page = fixtures._single_page()
    row = page["rows"][0]
    payload = row["payload"]
    payload.update(
        status="delisted",
        status_as_of="2026-10-22",
        known_start_date="1991-01-01",
        start_boundary_unknown=False,
        start_evidence_ref="TEST-204-START",
        delisted_on="2026-10-20",
        delist_evidence_ref="TEST-204-DELIST",
    )
    fixtures._rehash_row(row)

    result = await fixtures._client(
        httpx.MockTransport(lambda _: fixtures._response(page))
    ).list_options()

    items = result["items"]
    assert isinstance(items, list)
    item = items[0]
    assert isinstance(item, dict)
    assert item["lifecycle_status"] == "delisted"
    assert item["status_as_of"] == "2026-10-22"


@pytest.mark.parametrize(
    ("known_start_date", "status_as_of", "delisted_on"),
    [
        ("2026-10-21", "2026-10-22", "2026-10-20"),
        ("1991-01-01", "2026-10-19", "2026-10-20"),
    ],
)
async def test_delisted_lifecycle_dates_must_be_chronologically_consistent(
    known_start_date: str,
    status_as_of: str,
    delisted_on: str,
) -> None:
    page = fixtures._single_page()
    row = page["rows"][0]
    row["payload"].update(
        status="delisted",
        known_start_date=known_start_date,
        start_boundary_unknown=False,
        start_evidence_ref="TEST-204-START",
        status_as_of=status_as_of,
        delisted_on=delisted_on,
        delist_evidence_ref="TEST-204-DELIST",
    )
    fixtures._rehash_row(row)

    with pytest.raises(fixtures.InstrumentReferenceError) as raised:
        await fixtures._client(
            httpx.MockTransport(lambda _: fixtures._response(page))
        ).list_options()

    assert raised.value.code == "OPENDATA_REFERENCE_PROTOCOL_INVALID"


@pytest.mark.parametrize(
    ("alias_text", "page_index"),
    [("TEST_XSHG_A", 0), ("600001", 0), ("TEST_XSHE_B", 1)],
)
async def test_alias_cannot_collide_with_another_instruments_identity(
    alias_text: str, page_index: int
) -> None:
    pages = copy.deepcopy(fixtures._fixture()["pages"])
    row = pages[page_index]["rows"][0]
    alias = copy.deepcopy(row["payload"]["aliases"][0])
    alias.update(alias=alias_text, valid_from=None, valid_through=None)
    row["payload"]["aliases"].append(alias)
    fixtures._rehash_row(row)

    with pytest.raises(fixtures.InstrumentReferenceError) as raised:
        await fixtures._client(fixtures._pages_transport(pages)).list_options()

    assert raised.value.code == "OPENDATA_REFERENCE_PROTOCOL_INVALID"


@pytest.mark.parametrize(
    "alias_error", ["keys", "evidence", "date", "end-date", "interval", "count"]
)
async def test_alias_claims_require_bounded_well_formed_evidence(alias_error: str) -> None:
    page = fixtures._single_page()
    row = page["rows"][0]
    aliases = row["payload"]["aliases"]
    if alias_error == "keys":
        del aliases[0]["evidence_ref"]
    elif alias_error == "evidence":
        aliases[0]["evidence_ref"] = "https://private.invalid/evidence"
    elif alias_error == "date":
        aliases[0]["valid_from"] = "2020-02-30"
    elif alias_error == "end-date":
        aliases[0]["valid_through"] = "2020-02-30"
    elif alias_error == "interval":
        aliases[0]["valid_from"] = "2021-01-01"
        aliases[0]["valid_through"] = "2020-01-01"
    else:
        aliases.extend(copy.deepcopy(aliases[0]) for _ in range(16))
    fixtures._rehash_row(row)

    with pytest.raises(fixtures.InstrumentReferenceError) as raised:
        await fixtures._client(
            httpx.MockTransport(lambda _: fixtures._response(page))
        ).list_options()

    assert raised.value.code == "OPENDATA_REFERENCE_PROTOCOL_INVALID"
    assert "private.invalid" not in str(raised.value)


async def test_registry_version_cannot_change_inside_a_pinned_snapshot() -> None:
    pages = copy.deepcopy(fixtures._fixture()["pages"])
    pages[1]["rows"][0]["payload"]["registry_version"] = "other-registry-v1"
    fixtures._rehash_row(pages[1]["rows"][0])

    with pytest.raises(fixtures.InstrumentReferenceError) as raised:
        await fixtures._client(fixtures._pages_transport(pages)).list_options(
            search="SYNTHETIC Alpha"
        )

    assert raised.value.code == "OPENDATA_REFERENCE_PROTOCOL_INVALID"
