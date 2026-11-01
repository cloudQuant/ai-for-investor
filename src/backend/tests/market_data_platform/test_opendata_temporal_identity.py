"""Offline contract tests for the explicitly pinned OpenData identity client."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Mapping
from dataclasses import replace
from datetime import date, datetime, timedelta
from typing import Any

import httpx
import pytest

from app.services.market_data.opendata_credentials import OpendataCredentials
from app.services.market_data.opendata_temporal_identity import (
    OpendataTemporalIdentityClient,
    OpendataTemporalIdentityConfig,
    OpendataTemporalIdentityError,
    OpendataTemporalIdentityLimits,
    OpendataTemporalIdentityPin,
    TemporalIdentityPair,
)

_API_KEY = "synthetic-client-key"
_DATASET_ID = "instrument.identity"
_SOURCE_ID = "akshare"
_AUTHORITY_ID = "reviewed-market-authority"
_REGISTRY_ID = "cn-a-share"
_REFERENCE_VERSION = "identity-reference-v1"
_SNAPSHOT_SHA256 = "a" * 64
_PATH = "/api/v2/identity/resolve"
_START = date(2020, 1, 1)
_END = date(2020, 1, 5)


def _pin(**changes: str) -> OpendataTemporalIdentityPin:
    values = {
        "dataset_id": _DATASET_ID,
        "source_id": _SOURCE_ID,
        "authority_id": _AUTHORITY_ID,
        "registry_id": _REGISTRY_ID,
        "reference_version": _REFERENCE_VERSION,
        "snapshot_sha256": _SNAPSHOT_SHA256,
    }
    values.update(changes)
    return OpendataTemporalIdentityPin(**values)


def _config(**pin_changes: str) -> OpendataTemporalIdentityConfig:
    credentials = OpendataCredentials(_API_KEY, base_url="http://127.0.0.1:8123")
    return OpendataTemporalIdentityConfig(credentials=credentials, pin=_pin(**pin_changes))


def _pair_document() -> dict[str, Any]:
    return {
        "dataset_id": _DATASET_ID,
        "authority_id": _AUTHORITY_ID,
        "registry_id": _REGISTRY_ID,
        "reference_version": _REFERENCE_VERSION,
        "snapshot_sha256": _SNAPSHOT_SHA256,
        "subject": "pair",
        "pair": {"exchange": "XSHG", "symbol": "600519"},
        "instrument_id": None,
        "window": {
            "start": _START.isoformat(),
            "end_exclusive": _END.isoformat(),
            "semantics": "half_open_calendar_dates",
        },
        "segments": [
            {
                "start": "2020-01-01",
                "end_exclusive": "2020-01-02",
                "status": "unknown",
                "assignment_id": None,
                "instrument_id": None,
                "pair": None,
                "source_id": None,
                "source_version": None,
            },
            {
                "start": "2020-01-02",
                "end_exclusive": "2020-01-04",
                "status": "known",
                "assignment_id": "assignment-1",
                "instrument_id": "instrument-600519",
                "pair": {"exchange": "XSHG", "symbol": "600519"},
                "source_id": _SOURCE_ID,
                "source_version": "review-v1",
            },
            {
                "start": "2020-01-04",
                "end_exclusive": "2020-01-05",
                "status": "unknown",
                "assignment_id": None,
                "instrument_id": None,
                "pair": None,
                "source_id": None,
                "source_version": None,
            },
        ],
        "completeness": "not_established_by_identity_resolution",
        "source_integrity": "snapshot_bytes_pinned_source_evidence_not_authenticated",
    }


def _instrument_document() -> dict[str, Any]:
    document = _pair_document()
    document["subject"] = "instrument"
    document["pair"] = None
    document["instrument_id"] = "instrument-600519"
    known = document["segments"][1]
    known["instrument_id"] = "instrument-600519"
    return document


def _response(
    document: object,
    *,
    status: int = 200,
    headers: Mapping[str, str] | None = None,
) -> httpx.Response:
    wire_headers = {"content-type": "application/json", **dict(headers or {})}
    body = json.dumps(document, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode(
        "utf-8"
    )
    wire_headers.setdefault("content-length", str(len(body)))
    return httpx.Response(
        status,
        headers=wire_headers,
        stream=_TrackingStream([body] if body else []),
    )


def _client(
    transport: httpx.AsyncBaseTransport,
    *,
    limits: OpendataTemporalIdentityLimits | None = None,
    config: OpendataTemporalIdentityConfig | None = None,
) -> OpendataTemporalIdentityClient:
    return OpendataTemporalIdentityClient(config or _config(), transport=transport, limits=limits)


class _TrackingStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.read_count = 0
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self.chunks:
            self.read_count += 1
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


def _resolve_pair(
    client: OpendataTemporalIdentityClient,
    *,
    start: date = _START,
    end: date = _END,
) -> Any:
    return client.resolve_pair(
        exchange="XSHG",
        symbol="600519",
        window_start=start,
        window_end_exclusive=end,
    )


def _resolve_instrument(
    client: OpendataTemporalIdentityClient,
    *,
    start: date = _START,
    end: date = _END,
) -> Any:
    return client.resolve_instrument(
        instrument_id="instrument-600519",
        window_start=start,
        window_end_exclusive=end,
    )


class TestConfiguration:
    def test_api_key_does_not_appear_in_config_or_client_repr(self) -> None:
        client = OpendataTemporalIdentityClient(_config())

        assert _API_KEY not in repr(_config())
        assert _API_KEY not in repr(client)

    @pytest.mark.parametrize(
        "base_url",
        [
            "",
            "http://example.test",
            "http://127.0.0.1/path",
            "http://127.0.0.1?tenant=x",
            "http://user:password@127.0.0.1",
            "https://example.test/#fragment",
            "https://example.test:not-a-port",
        ],
    )
    def test_rejects_ambiguous_or_insecure_origin(self, base_url: str) -> None:
        credentials = OpendataCredentials(_API_KEY, base_url=base_url or "http://127.0.0.1")
        if not base_url:
            credentials.base_url = ""

        with pytest.raises(OpendataTemporalIdentityError) as raised:
            OpendataTemporalIdentityConfig(credentials=credentials, pin=_pin())

        assert raised.value.code == "OPENDATA_TEMPORAL_IDENTITY_CONFIG_INVALID"
        assert _API_KEY not in repr(raised.value)

    @pytest.mark.parametrize(
        "changes",
        [
            {"dataset_id": "bad dataset"},
            {"source_id": ""},
            {"authority_id": "x" * 129},
            {"snapshot_sha256": "A" * 64},
            {"snapshot_sha256": "not-a-digest"},
        ],
    )
    def test_rejects_invalid_operator_pin(self, changes: dict[str, str]) -> None:
        with pytest.raises(OpendataTemporalIdentityError) as raised:
            _pin(**changes)

        assert raised.value.code == "OPENDATA_TEMPORAL_IDENTITY_CONFIG_INVALID"
        assert all(not value or value not in repr(raised.value) for value in changes.values())

    @pytest.mark.parametrize(
        "changes",
        [
            {"max_request_bytes": 0},
            {"max_response_bytes": 512 * 1024 + 1},
            {"max_segments": True},
            {"deadline_seconds": 0},
            {"request_timeout_seconds": 2.01},
        ],
    )
    def test_limits_cannot_exceed_fixed_contract_ceilings(self, changes: dict[str, object]) -> None:
        with pytest.raises(OpendataTemporalIdentityError) as raised:
            replace(OpendataTemporalIdentityLimits(), **changes)

        assert raised.value.code == "OPENDATA_TEMPORAL_IDENTITY_CONFIG_INVALID"


class TestRequestContract:
    async def test_pair_request_sends_exact_trusted_pin_and_half_open_query(self) -> None:
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return _response(_pair_document())

        result = await _resolve_pair(_client(httpx.MockTransport(handler)))

        assert len(requests) == 1
        request = requests[0]
        assert request.method == "POST"
        assert request.url.path == _PATH
        assert request.url.query == b""
        assert request.headers["x-api-key"] == _API_KEY
        assert request.headers["accept-encoding"] == "identity"
        assert json.loads(request.content) == {
            "dataset_id": _DATASET_ID,
            "authority_id": _AUTHORITY_ID,
            "registry_id": _REGISTRY_ID,
            "reference_version": _REFERENCE_VERSION,
            "snapshot_sha256": _SNAPSHOT_SHA256,
            "window_start": "2020-01-01",
            "window_end_exclusive": "2020-01-05",
            "exchange": "XSHG",
            "symbol": "600519",
            "instrument_id": None,
        }
        assert len(request.content) <= 8 * 1024
        assert result.subject == "pair"
        assert result.pair == TemporalIdentityPair("XSHG", "600519")
        assert result.window_start == _START
        assert result.window_end_exclusive == _END

    async def test_instrument_request_uses_only_the_opaque_instrument_selector(self) -> None:
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return _response(_instrument_document())

        result = await _resolve_instrument(_client(httpx.MockTransport(handler)))
        body = json.loads(requests[0].content)

        assert body["instrument_id"] == "instrument-600519"
        assert body["exchange"] is None
        assert body["symbol"] is None
        assert result.subject == "instrument"
        assert result.pair is None
        assert result.instrument_id == "instrument-600519"

    @pytest.mark.parametrize(
        "arguments",
        [
            {"exchange": "XSHG", "symbol": None, "instrument_id": None},
            {"exchange": "SH", "symbol": "600519", "instrument_id": None},
            {"exchange": "XSHG", "symbol": "60051x", "instrument_id": None},
        ],
    )
    async def test_invalid_pair_selectors_fail_before_transport(
        self, arguments: dict[str, object]
    ) -> None:
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return _response(_pair_document())

        client = _client(httpx.MockTransport(handler))
        with pytest.raises(OpendataTemporalIdentityError) as raised:
            await client.resolve_pair(
                exchange=arguments.get("exchange"),  # type: ignore[arg-type]
                symbol=arguments.get("symbol"),  # type: ignore[arg-type]
                window_start=_START,
                window_end_exclusive=_END,
            )

        assert raised.value.code == "OPENDATA_TEMPORAL_IDENTITY_QUERY_INVALID"
        assert requests == []

    async def test_invalid_instrument_selector_fails_before_transport(self) -> None:
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return _response(_instrument_document())

        client = _client(httpx.MockTransport(handler))
        with pytest.raises(OpendataTemporalIdentityError) as raised:
            await client.resolve_instrument(
                instrument_id="bad instrument",
                window_start=_START,
                window_end_exclusive=_END,
            )

        assert raised.value.code == "OPENDATA_TEMPORAL_IDENTITY_QUERY_INVALID"
        assert requests == []

    @pytest.mark.parametrize(
        ("start", "end"),
        [
            (_END, _START),
            (_START, _START),
            (datetime(2020, 1, 1), _END),
            (_START, date(2031, 1, 1)),
        ],
    )
    async def test_invalid_or_oversized_windows_fail_before_transport(
        self, start: date, end: date
    ) -> None:
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return _response(_pair_document())

        with pytest.raises(OpendataTemporalIdentityError) as raised:
            await _resolve_pair(_client(httpx.MockTransport(handler)), start=start, end=end)

        assert raised.value.code == "OPENDATA_TEMPORAL_IDENTITY_QUERY_INVALID"
        assert requests == []


class TestResponseContract:
    async def test_preserves_unknown_and_known_segments_with_source_and_date_bounds(self) -> None:
        client = _client(httpx.MockTransport(lambda _: _response(_pair_document())))

        result = await _resolve_pair(client)

        assert len(result.segments) == 3
        assert [segment.status for segment in result.segments] == [
            "unknown",
            "known",
            "unknown",
        ]
        assert result.segments[0].start == _START
        assert result.segments[-1].end_exclusive == _END
        known = result.segments[1]
        assert known.assignment_id == "assignment-1"
        assert known.instrument_id == "instrument-600519"
        assert known.pair == TemporalIdentityPair("XSHG", "600519")
        assert known.source_id == _SOURCE_ID
        assert known.source_version == "review-v1"
        assert result.completeness == "not_established_by_identity_resolution"
        assert result.source_integrity == "snapshot_bytes_pinned_source_evidence_not_authenticated"

    @pytest.mark.parametrize(
        "mutation",
        [
            lambda body: body.update(snapshot_sha256="b" * 64),
            lambda body: body.update(authority_id="other-authority"),
            lambda body: body.update(subject="instrument"),
            lambda body: body["window"].update(end_exclusive="2020-01-04"),
            lambda body: body["window"].update(semantics="inclusive"),
            lambda body: body.update(completeness="complete"),
            lambda body: body.update(source_integrity="verified"),
            lambda body: body.update(unreviewed_extra="value"),
        ],
    )
    async def test_rejects_unpinned_or_unrequested_response_metadata(self, mutation: Any) -> None:
        document = _pair_document()
        mutation(document)
        client = _client(httpx.MockTransport(lambda _: _response(document)))

        with pytest.raises(OpendataTemporalIdentityError) as raised:
            await _resolve_pair(client)

        assert raised.value.code == "OPENDATA_TEMPORAL_IDENTITY_PROTOCOL_INVALID"
        assert _API_KEY not in repr(raised.value)

    @pytest.mark.parametrize(
        "mutate_segments",
        [
            lambda rows: rows[1].update(start="2020-01-03"),
            lambda rows: rows[1].update(end_exclusive="2020-01-05"),
            lambda rows: rows[1].update(pair={"exchange": "XSHE", "symbol": "600519"}),
            lambda rows: rows[1].update(source_id="other-source"),
            lambda rows: rows[1].update(source_version="bad version"),
            lambda rows: rows[1].update(instrument_id=None),
            lambda rows: rows[0].update(instrument_id="hidden-id"),
            lambda rows: rows[0].update(source_id="hidden-source"),
            lambda rows: rows[0].update(assignment_id="hidden-assignment"),
            lambda rows: rows[1].update(status="maybe"),
        ],
    )
    async def test_rejects_gapped_overlapping_or_semantically_invalid_segments(
        self, mutate_segments: Any
    ) -> None:
        document = _pair_document()
        mutate_segments(document["segments"])
        client = _client(httpx.MockTransport(lambda _: _response(document)))

        with pytest.raises(OpendataTemporalIdentityError) as raised:
            await _resolve_pair(client)

        assert raised.value.code == "OPENDATA_TEMPORAL_IDENTITY_PROTOCOL_INVALID"

    async def test_instrument_resolution_requires_each_known_assignment_to_match_query(
        self,
    ) -> None:
        document = _instrument_document()
        document["segments"][1]["instrument_id"] = "another-instrument"
        client = _client(httpx.MockTransport(lambda _: _response(document)))

        with pytest.raises(OpendataTemporalIdentityError) as raised:
            await _resolve_instrument(client)

        assert raised.value.code == "OPENDATA_TEMPORAL_IDENTITY_PROTOCOL_INVALID"

    async def test_rejects_more_segments_than_the_client_budget(self) -> None:
        document = _pair_document()
        document["segments"] = [
            {
                "start": (date(2020, 1, 1) + timedelta(days=index)).isoformat(),
                "end_exclusive": (date(2020, 1, 1) + timedelta(days=index + 1)).isoformat(),
                "status": "unknown",
                "assignment_id": None,
                "instrument_id": None,
                "pair": None,
                "source_id": None,
                "source_version": None,
            }
            for index in range(4)
        ]
        document["window"]["end_exclusive"] = "2020-01-05"
        limits = replace(OpendataTemporalIdentityLimits(), max_segments=2)
        client = _client(httpx.MockTransport(lambda _: _response(document)), limits=limits)

        with pytest.raises(OpendataTemporalIdentityError) as raised:
            await _resolve_pair(client)

        assert raised.value.code == "OPENDATA_TEMPORAL_IDENTITY_LIMIT_EXCEEDED"


class TestWireSafety:
    @pytest.mark.parametrize(
        ("headers", "body", "code"),
        [
            ({"content-type": "text/plain"}, b"{}", "OPENDATA_TEMPORAL_IDENTITY_PROTOCOL_INVALID"),
            (
                {"content-type": "application/json", "content-encoding": "gzip"},
                b"{}",
                "OPENDATA_TEMPORAL_IDENTITY_PROTOCOL_INVALID",
            ),
            (
                {"content-type": "application/json", "content-length": "-1"},
                b"{}",
                "OPENDATA_TEMPORAL_IDENTITY_PROTOCOL_INVALID",
            ),
            (
                {"content-type": "application/json", "content-length": "524289"},
                b"{}",
                "OPENDATA_TEMPORAL_IDENTITY_LIMIT_EXCEEDED",
            ),
        ],
    )
    async def test_rejects_invalid_headers_without_echoing_body_or_key(
        self, headers: dict[str, str], body: bytes, code: str
    ) -> None:
        response = httpx.Response(
            200,
            headers=headers,
            stream=_TrackingStream([body] if body else []),
        )
        client = _client(httpx.MockTransport(lambda _: response))

        with pytest.raises(OpendataTemporalIdentityError) as raised:
            await _resolve_pair(client)

        assert raised.value.code == code
        assert _API_KEY not in str(raised.value)
        assert not body or body.decode("ascii") not in str(raised.value)

    @pytest.mark.parametrize(
        "body",
        [
            b"",
            b"not-json",
            b"[]",
            b'{"subject":"pair","subject":"instrument"}',
            b'{"number":NaN}',
            b"\xff",
        ],
    )
    async def test_rejects_malformed_duplicate_or_nonstandard_json(self, body: bytes) -> None:
        client = _client(
            httpx.MockTransport(
                lambda _: httpx.Response(
                    200,
                    headers={"content-type": "application/json"},
                    stream=_TrackingStream([body] if body else []),
                )
            )
        )

        with pytest.raises(OpendataTemporalIdentityError) as raised:
            await _resolve_pair(client)

        assert raised.value.code == "OPENDATA_TEMPORAL_IDENTITY_PROTOCOL_INVALID"
        assert _API_KEY not in repr(raised.value)
        assert not body or body[:32].decode("utf-8", errors="replace") not in repr(raised.value)

    async def test_streamed_oversize_response_is_bounded_and_closed(self) -> None:
        stream = _TrackingStream([b"x" * 80, b"y" * 80])
        response = httpx.Response(
            200,
            headers={"content-type": "application/json"},
            stream=stream,
        )
        limits = replace(OpendataTemporalIdentityLimits(), max_response_bytes=100)
        client = _client(httpx.MockTransport(lambda _: response), limits=limits)

        with pytest.raises(OpendataTemporalIdentityError) as raised:
            await _resolve_pair(client)

        assert raised.value.code == "OPENDATA_TEMPORAL_IDENTITY_LIMIT_EXCEEDED"
        assert stream.read_count == 2
        assert stream.closed is True

    @pytest.mark.parametrize("status", [301, 302, 401, 403, 404, 429, 500])
    async def test_http_errors_are_fixed_and_never_trigger_fallback(self, status: int) -> None:
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(status, headers={"location": "https://elsewhere.test"})

        client = _client(httpx.MockTransport(handler))
        with pytest.raises(OpendataTemporalIdentityError) as raised:
            await _resolve_pair(client)

        assert raised.value.code == "OPENDATA_TEMPORAL_IDENTITY_UNAVAILABLE"
        assert len(requests) == 1
        assert requests[0].url.host == "127.0.0.1"
        assert _API_KEY not in repr(raised.value)

    async def test_total_deadline_is_bounded_and_does_not_retry(self) -> None:
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            await asyncio.sleep(0.05)
            return _response(_pair_document())

        limits = replace(
            OpendataTemporalIdentityLimits(),
            deadline_seconds=0.01,
            request_timeout_seconds=0.5,
        )
        client = _client(httpx.MockTransport(handler), limits=limits)

        with pytest.raises(OpendataTemporalIdentityError) as raised:
            await _resolve_pair(client)

        assert raised.value.code == "OPENDATA_TEMPORAL_IDENTITY_LIMIT_EXCEEDED"
        assert len(requests) == 1
        assert _API_KEY not in repr(raised.value)
