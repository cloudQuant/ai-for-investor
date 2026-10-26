"""Offline tests for the bounded OpenData instrument-reference adapter."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import JsonValue

import app.services.market_data.opendata_instrument_reference as reference_module
from app.services.market_data.opendata_instrument_reference import (
    InstrumentReferenceClient,
    InstrumentReferenceConfig,
    InstrumentReferenceError,
    InstrumentReferenceLimits,
)

_FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "afi204_instrument_reference_v1.json"
_API_PATH = "/api/v2/datasets/fixture.instrument-reference.stock/records"
_API_KEY = "fixture-not-a-secret"


def _fixture() -> dict[str, Any]:
    return json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))


def _config() -> InstrumentReferenceConfig:
    fixture = _fixture()
    contract = fixture["contract"]
    return InstrumentReferenceConfig(
        base_url="http://127.0.0.1:8123",
        api_key=_API_KEY,
        dataset_id=contract["dataset_id"],
        source_id=contract["source"]["source_id"],
        contract_sha256=fixture["contract_sha256"],
    )


def _limits(**changes: object) -> InstrumentReferenceLimits:
    return replace(InstrumentReferenceLimits(), page_size=1, **changes)


def _clock() -> datetime:
    return datetime.fromisoformat(_fixture()["clock"])


def _client(
    transport: httpx.AsyncBaseTransport,
    *,
    limits: InstrumentReferenceLimits | None = None,
) -> InstrumentReferenceClient:
    return InstrumentReferenceClient(
        _config(),
        transport=transport,
        clock=_clock,
        limits=limits or _limits(),
    )


def _response(page: object, *, status: int = 200) -> httpx.Response:
    body = json.dumps(page, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode(
        "utf-8"
    )
    return _stream_response(
        body,
        status=status,
        headers={"content-type": "application/json"},
    )


def _stream_response(
    body: bytes,
    *,
    status: int = 200,
    headers: Mapping[str, str] | None = None,
) -> httpx.Response:
    response_headers = dict(headers or {})
    response_headers.setdefault("content-length", str(len(body)))
    return httpx.Response(status, headers=response_headers, stream=_BodyStream(body))


def _pages_transport(
    pages: list[dict[str, Any]],
    *,
    requests: list[httpx.Request] | None = None,
) -> httpx.MockTransport:
    async def handler(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(request)
        assert request.url.path == _API_PATH
        cursor = request.url.params.get("cursor")
        if cursor is None:
            return _response(copy.deepcopy(pages[0]))
        assert cursor == "synthetic-cursor-page-2"
        return _response(copy.deepcopy(pages[1]))

    return httpx.MockTransport(handler)


def _single_page() -> dict[str, Any]:
    page = copy.deepcopy(_fixture()["pages"][0])
    page["record_count"] = 1
    page["has_more"] = False
    page["next_cursor"] = None
    _sync_snapshot(page)
    return page


def _sync_snapshot(page: dict[str, Any]) -> None:
    page["meta"]["snapshot"] = {
        key: value
        for key, value in page.items()
        if key not in {"meta", "rows", "count", "next_cursor", "has_more"}
    }


def _rehash_row(row: dict[str, Any]) -> None:
    fields = (
        "business_key",
        "business_date",
        "event_at",
        "observed_at",
        "source_published_at",
        "available_at",
        "payload",
    )
    material = {key: row[key] for key in fields}
    encoded = json.dumps(
        material,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    row["record_hash"] = hashlib.sha256(encoded).hexdigest()


class _BodyStream(httpx.AsyncByteStream):
    def __init__(self, body: bytes) -> None:
        self.body = body

    async def __aiter__(self) -> AsyncIterator[bytes]:
        if self.body:
            yield self.body

    async def aclose(self) -> None:
        return None


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


class _BlockingStream(httpx.AsyncByteStream):
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        self.started.set()
        await self.release.wait()
        yield b"{}"

    async def aclose(self) -> None:
        self.closed = True


class TestConfigAndLimits:
    def test_api_key_is_hidden_from_config_repr(self) -> None:
        assert _API_KEY not in repr(_config())

    @pytest.mark.parametrize(
        "base_url",
        [
            "",
            "http://example.com",
            "http://127.0.0.1/path",
            "http://127.0.0.1?tenant=x",
            "http://user:password@127.0.0.1",
            "https://example.com/#fragment",
        ],
    )
    def test_rejects_unsafe_or_ambiguous_origin(self, base_url: str) -> None:
        with pytest.raises(InstrumentReferenceError) as raised:
            InstrumentReferenceConfig(
                base_url=base_url,
                api_key=_API_KEY,
                dataset_id="fixture.instrument-reference.stock",
                source_id="fixture.reference",
                contract_sha256="8dc2e5912f5a8c9e371beed3c36c772fe32914f59065d7655310a4e6e3be5c96",
            )
        assert raised.value.code == "OPENDATA_REFERENCE_CONFIG_INVALID"
        assert _API_KEY not in str(raised.value)

    @pytest.mark.parametrize(
        "changes",
        [
            {"page_size": 0},
            {"page_size": 101},
            {"max_pages": True},
            {"max_rows": 20_001},
            {"max_response_bytes": 2_097_153},
            {"max_total_bytes": 0},
            {"max_total_bytes": 16_777_217},
            {"deadline_seconds": 0},
            {"deadline_seconds": 5.01},
            {"request_timeout_seconds": 2.01},
            {"request_timeout_seconds": float("inf")},
        ],
    )
    def test_limits_are_positive_typed_and_capped(self, changes: dict[str, object]) -> None:
        with pytest.raises(InstrumentReferenceError) as raised:
            replace(InstrumentReferenceLimits(), **changes)
        assert raised.value.code == "OPENDATA_REFERENCE_CONFIG_INVALID"

    def test_timeout_limits_accept_frozen_maximum_values(self) -> None:
        limits = InstrumentReferenceLimits(deadline_seconds=5.0, request_timeout_seconds=2.0)
        assert limits.deadline_seconds == 5.0
        assert limits.request_timeout_seconds == 2.0

    def test_total_byte_budget_can_be_lower_than_per_response_budget(self) -> None:
        limits = InstrumentReferenceLimits(max_response_bytes=1024, max_total_bytes=512)
        assert limits.max_response_bytes == 1024
        assert limits.max_total_bytes == 512

    @pytest.mark.parametrize("limit", [0, -1, True, 81, 1.0])
    async def test_list_limit_rejects_bool_nonpositive_and_overlarge(self, limit: object) -> None:
        client = _client(httpx.MockTransport(lambda _: _response({})))
        with pytest.raises(InstrumentReferenceError) as raised:
            await client.list_options(limit=limit)  # type: ignore[arg-type]
        assert raised.value.code == "OPENDATA_REFERENCE_CONFIG_INVALID"

    async def test_datetime_is_not_accepted_as_effective_date(self) -> None:
        client = _client(httpx.MockTransport(lambda _: _response({})))
        with pytest.raises(InstrumentReferenceError) as raised:
            await client.list_options(effective_on=datetime(2026, 10, 22))  # type: ignore[arg-type]
        assert raised.value.code == "OPENDATA_REFERENCE_CONFIG_INVALID"


class TestSnapshotProtocol:
    async def test_fixture_snapshot_returns_only_safe_option_fields(self) -> None:
        fixture = _fixture()
        pages = fixture["pages"]
        requests: list[httpx.Request] = []
        client = _client(_pages_transport(pages, requests=requests))

        result = await client.list_options()

        assert result == fixture["options_response"]
        assert [request.url.path for request in requests] == [_API_PATH, _API_PATH]
        assert dict(requests[0].url.params) == {"page_size": "1"}
        assert dict(requests[1].url.params) == {
            "snapshot_id": pages[0]["snapshot_id"],
            "cursor": "synthetic-cursor-page-2",
        }
        assert all(request.headers["x-api-key"] == _API_KEY for request in requests)
        assert all(request.headers["accept-encoding"] == "identity" for request in requests)
        assert "payload" not in json.dumps(result)

    async def test_full_page_then_empty_terminal_page_is_rejected_as_incomplete(self) -> None:
        pages = copy.deepcopy(_fixture()["pages"])
        empty = copy.deepcopy(pages[1])
        empty["rows"] = []
        empty["count"] = 0
        empty["has_more"] = False
        empty["next_cursor"] = None
        _sync_snapshot(empty)
        transport = httpx.MockTransport(
            lambda request: _response(pages[0] if "cursor" not in request.url.params else empty)
        )

        with pytest.raises(InstrumentReferenceError) as raised:
            await _client(transport).list_options()
        assert raised.value.code == "OPENDATA_REFERENCE_PROTOCOL_INVALID"

    @pytest.mark.parametrize(
        ("mutate", "expected_code"),
        [
            (
                lambda page: page.update(contract_sha256="0" * 64),
                "OPENDATA_REFERENCE_PROTOCOL_INVALID",
            ),
            (lambda page: page.update(page_size=True), "OPENDATA_REFERENCE_PROTOCOL_INVALID"),
            (lambda page: page.update(count=2), "OPENDATA_REFERENCE_PROTOCOL_INVALID"),
            (lambda page: page.update(next_cursor=""), "OPENDATA_REFERENCE_PROTOCOL_INVALID"),
            (lambda page: page.update(has_more=1), "OPENDATA_REFERENCE_PROTOCOL_INVALID"),
            (
                lambda page: page["meta"]["snapshot"].update(sequence=2),
                "OPENDATA_REFERENCE_PROTOCOL_INVALID",
            ),
        ],
    )
    async def test_rejects_bad_page_metadata(
        self, mutate: Callable[[dict[str, Any]], None], expected_code: str
    ) -> None:
        page = copy.deepcopy(_fixture()["pages"][0])
        mutate(page)
        transport = httpx.MockTransport(lambda _: _response(page))

        with pytest.raises(InstrumentReferenceError) as raised:
            await _client(transport).list_options()
        assert raised.value.code == expected_code

    async def test_snapshot_metadata_must_be_repeated_exactly(self) -> None:
        pages = copy.deepcopy(_fixture()["pages"])
        pages[1]["content_sha256"] = "5" * 64
        _sync_snapshot(pages[1])

        with pytest.raises(InstrumentReferenceError) as raised:
            await _client(_pages_transport(pages)).list_options()
        assert raised.value.code == "OPENDATA_REFERENCE_PROTOCOL_INVALID"

    async def test_content_hash_is_pinned_as_server_attestation_not_rebuilt(self) -> None:
        pages = copy.deepcopy(_fixture()["pages"])
        for page in pages:
            page["content_sha256"] = "5" * 64
            _sync_snapshot(page)
        result = await _client(_pages_transport(pages)).list_options()
        assert result["provenance"]["content_sha256"] == "5" * 64  # type: ignore[index]

    async def test_rejects_duplicate_identity_symbol_and_wrong_row_hash(self) -> None:
        pages = copy.deepcopy(_fixture()["pages"])
        pages[1]["rows"][0]["payload"]["symbol"] = pages[0]["rows"][0]["payload"]["symbol"]
        _rehash_row(pages[1]["rows"][0])

        with pytest.raises(InstrumentReferenceError) as raised:
            await _client(_pages_transport(pages)).list_options()
        assert raised.value.code == "OPENDATA_REFERENCE_PROTOCOL_INVALID"

        pages = copy.deepcopy(_fixture()["pages"])
        pages[0]["rows"][0]["record_hash"] = "0" * 64
        with pytest.raises(InstrumentReferenceError) as raised:
            await _client(_pages_transport(pages)).list_options()
        assert raised.value.code == "OPENDATA_REFERENCE_PROTOCOL_INVALID"

    async def test_rejects_non_null_business_date_and_duplicate_json_keys(self) -> None:
        page = copy.deepcopy(_fixture()["pages"][0])
        page["rows"][0]["business_date"] = "2026-10-22"
        _rehash_row(page["rows"][0])
        with pytest.raises(InstrumentReferenceError) as raised:
            await _client(httpx.MockTransport(lambda _: _response(page))).list_options()
        assert raised.value.code == "OPENDATA_REFERENCE_PROTOCOL_INVALID"

        body = b'{"dataset_id":"safe","dataset_id":"secret"}'
        transport = httpx.MockTransport(
            lambda _: _stream_response(body, headers={"content-type": "application/json"})
        )
        with pytest.raises(InstrumentReferenceError) as raised:
            await _client(transport).list_options()
        assert raised.value.code == "OPENDATA_REFERENCE_PROTOCOL_INVALID"
        assert "secret" not in str(raised.value)

    async def test_nonrepeating_cursor_and_full_snapshot_row_budget(self) -> None:
        pages = copy.deepcopy(_fixture()["pages"])
        for page in pages:
            page["record_count"] = 3
            _sync_snapshot(page)
        pages[1]["next_cursor"] = "synthetic-cursor-page-2"
        pages[1]["has_more"] = True
        _sync_snapshot(pages[1])
        with pytest.raises(InstrumentReferenceError) as raised:
            await _client(_pages_transport(pages)).list_options()
        assert raised.value.code == "OPENDATA_REFERENCE_PROTOCOL_INVALID"

        with pytest.raises(InstrumentReferenceError) as raised:
            await _client(
                _pages_transport(copy.deepcopy(_fixture()["pages"])),
                limits=_limits(max_rows=1),
            ).list_options()
        assert raised.value.code == "OPENDATA_REFERENCE_LIMIT_EXCEEDED"

    async def test_page_budget_stops_before_requesting_a_prefix_as_complete(self) -> None:
        calls: list[str] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            calls.append("called")
            return _response(copy.deepcopy(_fixture()["pages"][0]))

        with pytest.raises(InstrumentReferenceError) as raised:
            await _client(
                httpx.MockTransport(handler),
                limits=_limits(max_pages=1),
            ).list_options()
        assert raised.value.code == "OPENDATA_REFERENCE_LIMIT_EXCEEDED"
        assert calls == ["called"]

    async def test_expired_snapshot_is_rejected_before_result(self) -> None:
        page = copy.deepcopy(_fixture()["pages"][0])
        page["expires_at"] = "2026-10-22T00:00:01+00:00"
        page["meta"]["snapshot"]["expires_at"] = page["expires_at"]
        with pytest.raises(InstrumentReferenceError) as raised:
            await _client(httpx.MockTransport(lambda _: _response(page))).list_options()
        assert raised.value.code == "OPENDATA_REFERENCE_PROTOCOL_INVALID"

    async def test_as_of_cannot_follow_snapshot_creation(self) -> None:
        page = copy.deepcopy(_fixture()["pages"][0])
        page["as_of"] = "2026-10-22T00:00:01+00:00"
        _sync_snapshot(page)

        with pytest.raises(InstrumentReferenceError) as raised:
            await _client(httpx.MockTransport(lambda _: _response(page))).list_options()
        assert raised.value.code == "OPENDATA_REFERENCE_PROTOCOL_INVALID"

    @pytest.mark.parametrize(
        "name",
        [
            "Company\u202eName",
            "Company\u0001Name",
            "N" * 129,
            " Company",
            "Company ",
        ],
    )
    async def test_instrument_name_requires_printable_trimmed_text(self, name: str) -> None:
        page = _single_page()
        row = page["rows"][0]
        row["payload"]["name"] = name
        _rehash_row(row)

        with pytest.raises(InstrumentReferenceError) as raised:
            await _client(httpx.MockTransport(lambda _: _response(page))).list_options()
        assert raised.value.code == "OPENDATA_REFERENCE_PROTOCOL_INVALID"

    async def test_instrument_name_allows_printable_internal_spaces(self) -> None:
        page = _single_page()
        row = page["rows"][0]
        row["payload"]["name"] = "Synthetic Company"
        _rehash_row(row)

        result = await _client(httpx.MockTransport(lambda _: _response(page))).list_options()
        items = result["items"]
        assert isinstance(items, list)
        assert items[0]["name"] == "Synthetic Company"

    async def test_sync_search_cannot_return_after_total_deadline(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        original_time = reference_module._monotonic_time
        original_build_options = reference_module._build_options
        offset = 0.0

        def monotonic_time() -> float:
            return original_time() + offset

        def expire_deadline_after_search(
            rows: list[dict[str, JsonValue]],
            pinned: Mapping[str, JsonValue],
            *,
            search: str,
            limit: int,
            effective_on: date | None,
            deadline: float,
        ) -> dict[str, JsonValue]:
            nonlocal offset
            result = original_build_options(
                rows,
                pinned,
                search=search,
                limit=limit,
                effective_on=effective_on,
                deadline=deadline,
            )
            offset = 10.0
            return result

        monkeypatch.setattr(reference_module, "_monotonic_time", monotonic_time)
        monkeypatch.setattr(reference_module, "_build_options", expire_deadline_after_search)

        with pytest.raises(InstrumentReferenceError) as raised:
            await _client(httpx.MockTransport(lambda _: _response(_single_page()))).list_options()
        assert raised.value.code == "OPENDATA_REFERENCE_LIMIT_EXCEEDED"

    async def test_snapshot_expiry_is_rechecked_after_search(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        original_build_options = reference_module._build_options
        expired = False
        expiry = datetime.fromisoformat(_single_page()["expires_at"])

        def clock() -> datetime:
            return expiry if expired else _clock()

        def expire_snapshot_after_search(
            rows: list[dict[str, JsonValue]],
            pinned: Mapping[str, JsonValue],
            *,
            search: str,
            limit: int,
            effective_on: date | None,
            deadline: float,
        ) -> dict[str, JsonValue]:
            nonlocal expired
            result = original_build_options(
                rows,
                pinned,
                search=search,
                limit=limit,
                effective_on=effective_on,
                deadline=deadline,
            )
            expired = True
            return result

        monkeypatch.setattr(reference_module, "_build_options", expire_snapshot_after_search)
        client = InstrumentReferenceClient(
            _config(),
            transport=httpx.MockTransport(lambda _: _response(_single_page())),
            clock=clock,
            limits=_limits(),
        )

        with pytest.raises(InstrumentReferenceError) as raised:
            await client.list_options()
        assert raised.value.code == "OPENDATA_REFERENCE_PROTOCOL_INVALID"

    async def test_large_disjoint_alias_intervals_use_bounded_sweep(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class CountingDate(date):
            comparisons = 0

            def __lt__(self, other: date) -> bool:
                type(self).comparisons += 1
                return super().__lt__(other)

            def __ge__(self, other: date) -> bool:
                type(self).comparisons += 1
                return super().__ge__(other)

            def __gt__(self, other: date) -> bool:
                type(self).comparisons += 1
                return super().__gt__(other)

            @classmethod
            def fromisoformat(cls, value: str) -> CountingDate:
                parsed = date.fromisoformat(value)
                return cls(parsed.year, parsed.month, parsed.day)

        monkeypatch.setattr(reference_module, "date", CountingDate)
        rows: list[dict[str, JsonValue]] = []
        first_day = date(1900, 1, 1)
        for index in range(2_000):
            start = first_day + timedelta(days=2 * index)
            end = start + timedelta(days=1)
            payload: dict[str, JsonValue] = {
                "instrument_id": f"SYNTHETIC-{index}",
                "symbol": f"{index:06d}",
                "profile_version": "fixture-profile-v1",
                "registry_version": "fixture-registry-v1",
                "registry_evidence_ref": "FIXTURE-REGISTRY",
                "aliases": [
                    {
                        "alias": "LEGACY",
                        "valid_from": start.isoformat(),
                        "valid_through": end.isoformat(),
                    }
                ],
            }
            rows.append({"payload": payload})

        reference_module._validate_registry(
            rows,
            dataset_id="fixture.instrument-reference.stock",
            deadline=reference_module._monotonic_time() + 5.0,
        )
        assert CountingDate.comparisons < len(rows) * 10

        last_alias = rows[-1]["payload"]["aliases"][0]
        previous_alias = rows[-2]["payload"]["aliases"][0]
        assert isinstance(last_alias, dict)
        assert isinstance(previous_alias, dict)
        last_alias["valid_from"] = previous_alias["valid_from"]
        with pytest.raises(InstrumentReferenceError) as raised:
            reference_module._validate_registry(
                rows,
                dataset_id="fixture.instrument-reference.stock",
                deadline=reference_module._monotonic_time() + 5.0,
            )
        assert raised.value.code == "OPENDATA_REFERENCE_PROTOCOL_INVALID"


class TestSearchAndAliases:
    async def test_alias_search_requires_explicit_date_and_preserves_evidence(self) -> None:
        client = _client(_pages_transport(copy.deepcopy(_fixture()["pages"])))
        with pytest.raises(InstrumentReferenceError) as raised:
            await client.list_options(search="HIST")
        assert raised.value.code == "OPENDATA_REFERENCE_EFFECTIVE_DATE_REQUIRED"

        result = await _client(_pages_transport(copy.deepcopy(_fixture()["pages"]))).list_options(
            search="HIST",
            effective_on=date(2015, 7, 1),
        )
        items = result["items"]
        assert isinstance(items, list)
        assert len(items) == 1
        assert items[0]["instrument_id"] == "TEST_XSHG_A"
        assert items[0]["matched_alias"] == {
            "alias": "HIST",
            "alias_version": "fixture-alias-1",
            "evidence_ref": "TEST-204-ALIAS",
            "valid_from": "2010-01-01",
            "valid_through": "2019-12-31",
        }

    async def test_alias_interval_is_inclusive_and_outside_interval_returns_empty(self) -> None:
        for effective_on in (date(2010, 1, 1), date(2019, 12, 31)):
            result = await _client(
                _pages_transport(copy.deepcopy(_fixture()["pages"]))
            ).list_options(
                search="HIST",
                effective_on=effective_on,
            )
            assert result["total"] == 1
            items = result["items"]
            assert isinstance(items, list)
            assert isinstance(items[0], dict)
            assert items[0]["instrument_id"] == "TEST_XSHG_A"
        result = await _client(_pages_transport(copy.deepcopy(_fixture()["pages"]))).list_options(
            search="HIST",
            effective_on=date(2020, 1, 1),
        )
        assert result["total"] == 1
        items = result["items"]
        assert isinstance(items, list)
        assert isinstance(items[0], dict)
        assert items[0]["instrument_id"] == "TEST_XSHE_B"
        result = await _client(_pages_transport(copy.deepcopy(_fixture()["pages"]))).list_options(
            search="HIST",
            effective_on=date(2009, 12, 31),
        )
        assert result["total"] == 0

    async def test_alias_identity_matching_preserves_registry_case(self) -> None:
        result = await _client(_pages_transport(copy.deepcopy(_fixture()["pages"]))).list_options(
            search="hist"
        )
        assert result["total"] == 0

    async def test_duplicate_overlapping_aliases_fail_the_complete_catalog(self) -> None:
        pages = copy.deepcopy(_fixture()["pages"])
        alias = copy.deepcopy(pages[0]["rows"][0]["payload"]["aliases"][0])
        alias["valid_from"] = "2019-01-01"
        pages[1]["rows"][0]["payload"]["aliases"].append(alias)
        _rehash_row(pages[1]["rows"][0])
        with pytest.raises(InstrumentReferenceError) as raised:
            await _client(_pages_transport(pages)).list_options()
        assert raised.value.code == "OPENDATA_REFERENCE_PROTOCOL_INVALID"

    async def test_search_output_limit_is_presentation_only_after_full_validation(self) -> None:
        requests: list[httpx.Request] = []
        transport = _pages_transport(copy.deepcopy(_fixture()["pages"]), requests=requests)
        result = await _client(transport).list_options(search="SYNTHETIC", limit=1)
        assert result["total"] == 2
        assert result["has_more"] is True
        assert len(result["items"]) == 1
        assert result["complete"] is True
        assert len(requests) == 2


class TestHttpSafetyAndResourceBounds:
    async def test_status_errors_never_echo_body_url_or_key(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return _stream_response(
                f"{_API_KEY} https://private.example/path credential-canary".encode(),
                status=503,
                headers={"content-type": "text/plain"},
            )

        with pytest.raises(InstrumentReferenceError) as raised:
            await _client(httpx.MockTransport(handler)).list_options()
        assert raised.value.code == "OPENDATA_REFERENCE_UNAVAILABLE"
        for secret in (_API_KEY, "private.example", "credential-canary"):
            assert secret not in str(raised.value)

    async def test_rate_limit_has_fixed_error(self) -> None:
        transport = httpx.MockTransport(
            lambda _: _stream_response(b"secret quota detail", status=429)
        )
        with pytest.raises(InstrumentReferenceError) as raised:
            await _client(transport).list_options()
        assert raised.value.code == "OPENDATA_REFERENCE_RATE_LIMITED"
        assert "secret" not in str(raised.value)

    async def test_redirects_are_not_followed(self) -> None:
        calls: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return _stream_response(
                b"", status=302, headers={"location": "https://attacker.invalid/collect"}
            )

        with pytest.raises(InstrumentReferenceError) as raised:
            await _client(httpx.MockTransport(handler)).list_options()
        assert raised.value.code == "OPENDATA_REFERENCE_UNAVAILABLE"
        assert len(calls) == 1

    async def test_stream_stops_after_budget_and_closes_response(self) -> None:
        stream = _TrackingStream([b"a" * 10, b"b" * 10, b"late-secret"])
        transport = httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                headers={"content-type": "application/json"},
                stream=stream,
            )
        )
        limits = _limits(max_response_bytes=15, max_total_bytes=10)

        with pytest.raises(InstrumentReferenceError) as raised:
            await _client(transport, limits=limits).list_options()
        assert raised.value.code == "OPENDATA_REFERENCE_LIMIT_EXCEEDED"
        assert stream.read_count == 2
        assert stream.closed is True

    async def test_compressed_response_is_rejected_before_body_read(self) -> None:
        stream = _TrackingStream([b"gzip-expansion-canary"])
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(
                200,
                headers={
                    "content-type": "application/json",
                    "content-encoding": "gzip",
                },
                stream=stream,
            )

        with pytest.raises(InstrumentReferenceError) as raised:
            await _client(httpx.MockTransport(handler)).list_options()
        assert raised.value.code == "OPENDATA_REFERENCE_PROTOCOL_INVALID"
        assert requests[0].headers["accept-encoding"] == "identity"
        assert stream.read_count == 0
        assert stream.closed is True

    async def test_cancellation_propagates_and_closes_stream(self) -> None:
        stream = _BlockingStream()
        transport = httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                headers={"content-type": "application/json"},
                stream=stream,
            )
        )
        task = asyncio.create_task(_client(transport).list_options())
        await asyncio.wait_for(stream.started.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert stream.closed is True

    async def test_concurrent_calls_have_independent_fresh_clients(self) -> None:
        both_entered = asyncio.Event()
        release = asyncio.Event()
        entered = 0

        async def handler(_: httpx.Request) -> httpx.Response:
            nonlocal entered
            entered += 1
            if entered == 2:
                both_entered.set()
            await release.wait()
            return _response(_single_page())

        client = _client(httpx.MockTransport(handler), limits=_limits(max_rows=1))
        first = asyncio.create_task(client.list_options())
        second = asyncio.create_task(client.list_options())
        await asyncio.wait_for(both_entered.wait(), timeout=1)
        release.set()
        results = await asyncio.gather(first, second)
        assert all(result["complete"] is True for result in results)

    async def test_http_error_stream_is_closed_without_reading_body(self) -> None:
        stream = _TrackingStream([b"secret", b"unread"])
        transport = httpx.MockTransport(
            lambda _: httpx.Response(
                500,
                headers={"content-type": "application/json"},
                stream=stream,
            )
        )
        with pytest.raises(InstrumentReferenceError):
            await _client(transport).list_options()
        assert stream.closed is True
        assert stream.read_count == 0

    async def test_total_deadline_is_enforced(self) -> None:
        async def handler(_: httpx.Request) -> httpx.Response:
            await asyncio.sleep(0.05)
            return _response(_single_page())

        with pytest.raises(InstrumentReferenceError) as raised:
            await _client(
                httpx.MockTransport(handler),
                limits=_limits(deadline_seconds=0.01, request_timeout_seconds=0.5),
            ).list_options()
        assert raised.value.code == "OPENDATA_REFERENCE_LIMIT_EXCEEDED"
