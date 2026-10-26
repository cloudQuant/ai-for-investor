"""Bounded AFI consumer for the reviewed OpenData instrument-reference snapshot.

This adapter has no environment, settings, database, provider, or cache access.
It validates a complete v1 latest-view snapshot before returning any options.
"""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import math
import re
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import quote, urlsplit

import httpx
from pydantic import JsonValue

_PROFILE_VERSION = "od.instrument-reference.v1"
_SCHEMA_VERSION = "1"
_SEMANTIC_VERSION = "1.0.0"
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+\-]{0,127}$", re.ASCII)
_EVIDENCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$", re.ASCII)
_SYMBOL = re.compile(r"^[0-9]{6}$", re.ASCII)
_SHA256 = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_ERROR_CODES = frozenset(
    {
        "OPENDATA_REFERENCE_UNAVAILABLE",
        "OPENDATA_REFERENCE_PROTOCOL_INVALID",
        "OPENDATA_REFERENCE_LIMIT_EXCEEDED",
        "OPENDATA_REFERENCE_EFFECTIVE_DATE_REQUIRED",
        "OPENDATA_REFERENCE_CONFIG_INVALID",
        "OPENDATA_REFERENCE_RATE_LIMITED",
    }
)
_PROTOCOL_INVALID = "OPENDATA_REFERENCE_PROTOCOL_INVALID"
_UNAVAILABLE = "OPENDATA_REFERENCE_UNAVAILABLE"
_LIMIT_EXCEEDED = "OPENDATA_REFERENCE_LIMIT_EXCEEDED"
_EFFECTIVE_DATE_REQUIRED = "OPENDATA_REFERENCE_EFFECTIVE_DATE_REQUIRED"
_CONFIG_INVALID = "OPENDATA_REFERENCE_CONFIG_INVALID"
_RATE_LIMITED = "OPENDATA_REFERENCE_RATE_LIMITED"
_PAGE_PATH_PREFIX = "/api/v2/datasets/"
_PAGE_PATH_SUFFIX = "/records"
_MAX_SEARCH_CHARS = 128

_SCHEMA: tuple[tuple[str, str, bool], ...] = (
    ("profile_version", "string", False),
    ("registry_version", "string", False),
    ("registry_evidence_ref", "string", False),
    ("instrument_id", "string", False),
    ("asset_type", "string", False),
    ("symbol", "string", False),
    ("name", "string", False),
    ("market", "string", False),
    ("exchange", "string", False),
    ("lifecycle_version", "string", False),
    ("status", "string", False),
    ("status_as_of", "date", False),
    ("status_evidence_ref", "string", False),
    ("known_start_date", "date", True),
    ("start_boundary_unknown", "boolean", False),
    ("start_evidence_ref", "string", True),
    ("delisted_on", "date", True),
    ("delist_evidence_ref", "string", True),
    ("aliases", "array", False),
)
_IDENTITY_SEMANTICS: dict[str, JsonValue] = {
    "version": 1,
    "business_key_fields": ["instrument_id"],
    "identity_key_encoding": "canonical-json-array-v1",
    "revision": "latest non-deleted revision per business_key at the pinned publication sequence",
    "ordering_fields": ["instrument_id"],
    "storage_order": [
        {
            "field": "business_date",
            "direction": "asc",
            "nulls": "last",
            "comparison": "native",
        },
        {
            "field": "business_key",
            "direction": "asc",
            "comparison": "binary_lexicographic",
        },
    ],
    "temporal_semantics": "none",
    "time_field": None,
    "temporal_fields": {
        "business_date": "null for atemporal table records; not a historical business date",
        "observed_at": "source observation time",
        "source_published_at": "source publication time",
        "available_at": "platform availability time",
        "event_at": "source event time",
    },
}
_STORAGE_ORDER: list[JsonValue] = [
    {
        "field": "business_date",
        "direction": "asc",
        "nulls": "last",
        "comparison": "native",
    },
    {
        "field": "business_key",
        "direction": "asc",
        "comparison": "binary_lexicographic",
    },
]
_PAGE_KEYS = frozenset(
    {
        "dataset_id",
        "publication_id",
        "sequence",
        "schema_version",
        "semantic_version",
        "contract_sha256",
        "source",
        "schema",
        "quality",
        "field_units",
        "field_currencies",
        "field_adjustments",
        "currency",
        "adjustment_basis",
        "asset_class",
        "frequency",
        "record_kind",
        "filter_fields",
        "time_field",
        "temporal_semantics",
        "source_available_at_field",
        "calendar_id",
        "timezone",
        "pit_policy",
        "business_key_fields",
        "ordering_fields",
        "storage_order",
        "identity_key_encoding",
        "as_of",
        "snapshot_id",
        "window",
        "page_size",
        "created_at",
        "expires_at",
        "record_count",
        "selection_sha256",
        "content_sha256",
        "identity_semantics",
        "rows",
        "count",
        "next_cursor",
        "has_more",
        "meta",
    }
)
_ROW_KEYS = frozenset(
    {
        "dataset_id",
        "business_key",
        "business_date",
        "event_at",
        "observed_at",
        "source_published_at",
        "available_at",
        "payload",
        "revision",
        "publication_id",
        "publication_sequence",
        "record_hash",
    }
)
_PAYLOAD_KEYS = frozenset(
    {
        "profile_version",
        "registry_version",
        "registry_evidence_ref",
        "instrument_id",
        "asset_type",
        "symbol",
        "name",
        "market",
        "exchange",
        "lifecycle_version",
        "status",
        "status_as_of",
        "status_evidence_ref",
        "known_start_date",
        "start_boundary_unknown",
        "start_evidence_ref",
        "delisted_on",
        "delist_evidence_ref",
        "aliases",
    }
)
_ALIAS_KEYS = frozenset({"alias", "alias_version", "evidence_ref", "valid_from", "valid_through"})


class InstrumentReferenceError(RuntimeError):
    """Fixed-code error for safe adapter failures; upstream data is never attached."""

    def __init__(self, code: str) -> None:
        self.code = code if isinstance(code, str) and code in _ERROR_CODES else _PROTOCOL_INVALID
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class InstrumentReferenceConfig:
    """Explicit server-owned configuration for the instrument catalog client."""

    base_url: str
    api_key: str = field(repr=False)
    dataset_id: str
    source_id: str
    contract_sha256: str

    def __post_init__(self) -> None:
        _validate_origin(self.base_url)
        if not _valid_identifier(self.dataset_id) or not _valid_identifier(self.source_id):
            raise InstrumentReferenceError(_CONFIG_INVALID)
        if not _valid_text(self.api_key, maximum=1024) or self.api_key != self.api_key.strip():
            raise InstrumentReferenceError(_CONFIG_INVALID)
        if _SHA256.fullmatch(self.contract_sha256) is None:
            raise InstrumentReferenceError(_CONFIG_INVALID)


@dataclass(frozen=True, slots=True)
class InstrumentReferenceLimits:
    """Hard client-side limits; each configured value must stay within the v1 ceiling."""

    page_size: int = 100
    max_pages: int = 200
    max_rows: int = 20_000
    max_response_bytes: int = 2_097_152
    max_total_bytes: int = 16_777_216
    deadline_seconds: float = 5.0
    request_timeout_seconds: float = 2.0
    ui_limit_max: int = 80

    def __post_init__(self) -> None:
        integer_limits = (
            ("page_size", self.page_size, 100),
            ("max_pages", self.max_pages, 200),
            ("max_rows", self.max_rows, 20_000),
            ("max_response_bytes", self.max_response_bytes, 2_097_152),
            ("max_total_bytes", self.max_total_bytes, 16_777_216),
            ("ui_limit_max", self.ui_limit_max, 80),
        )
        if any(
            type(value) is not int or not 1 <= value <= ceiling
            for _, value, ceiling in integer_limits
        ):
            raise InstrumentReferenceError(_CONFIG_INVALID)
        for value, ceiling in (
            (self.deadline_seconds, 5.0),
            (self.request_timeout_seconds, 2.0),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value <= 0
                or value > ceiling
            ):
                raise InstrumentReferenceError(_CONFIG_INVALID)


class _BorrowedTransport(httpx.AsyncBaseTransport):
    """Let each fresh AsyncClient close its wrapper without owning injected transport."""

    def __init__(self, transport: httpx.AsyncBaseTransport) -> None:
        self._transport = transport

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return await self._transport.handle_async_request(request)

    async def aclose(self) -> None:
        return None


class InstrumentReferenceClient:
    """Read and validate a whole OpenData v1 latest-view instrument snapshot."""

    def __init__(
        self,
        config: InstrumentReferenceConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], datetime] | None = None,
        limits: InstrumentReferenceLimits | None = None,
    ) -> None:
        if not isinstance(config, InstrumentReferenceConfig):
            raise InstrumentReferenceError(_CONFIG_INVALID)
        if transport is not None and not isinstance(transport, httpx.AsyncBaseTransport):
            raise InstrumentReferenceError(_CONFIG_INVALID)
        if clock is not None and not callable(clock):
            raise InstrumentReferenceError(_CONFIG_INVALID)
        if limits is not None and not isinstance(limits, InstrumentReferenceLimits):
            raise InstrumentReferenceError(_CONFIG_INVALID)
        self._config = config
        self._transport = transport
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._limits = limits or InstrumentReferenceLimits()
        self._origin = _validate_origin(config.base_url)

    async def list_options(
        self,
        *,
        search: str = "",
        limit: int = 80,
        effective_on: date | None = None,
    ) -> dict[str, JsonValue]:
        """Return filtered options only after the full snapshot passes validation.

        V1 reads the current published latest-view snapshot. It is not a historic
        point-in-time catalog or a claim about price/history availability.
        """
        _validate_query(search, limit, effective_on, self._limits)
        try:
            result = await asyncio.wait_for(
                self._fetch_validate_and_select(search, limit, effective_on),
                timeout=self._limits.deadline_seconds,
            )
        except InstrumentReferenceError:
            raise
        except asyncio.CancelledError:
            raise
        except asyncio.TimeoutError:
            raise InstrumentReferenceError(_LIMIT_EXCEEDED) from None
        except Exception:
            raise InstrumentReferenceError(_UNAVAILABLE) from None
        return result

    async def _fetch_validate_and_select(
        self, search: str, limit: int, effective_on: date | None
    ) -> dict[str, JsonValue]:
        started = _monotonic_time()
        deadline = started + self._limits.deadline_seconds
        now = _clock_now(self._clock)
        page_count = 0
        rows: list[dict[str, JsonValue]] = []
        total_bytes = 0
        next_cursor: str | None = None
        seen_cursors: set[str] = set()
        pinned: dict[str, JsonValue] | None = None
        previous_business_key: bytes | None = None
        request_params: dict[str, str | int] = {"page_size": self._limits.page_size}
        path = _PAGE_PATH_PREFIX + quote(self._config.dataset_id, safe="") + _PAGE_PATH_SUFFIX
        headers = {"X-API-Key": self._config.api_key, "Accept": "application/json"}
        borrowed_transport = (
            _BorrowedTransport(self._transport) if self._transport is not None else None
        )

        client_options: dict[str, Any] = {
            "base_url": self._origin,
            "headers": {**headers, "Accept-Encoding": "identity"},
            "timeout": httpx.Timeout(self._limits.request_timeout_seconds),
            "trust_env": False,
            "follow_redirects": False,
            "limits": httpx.Limits(max_connections=2, max_keepalive_connections=1),
        }
        if borrowed_transport is not None:
            client_options["transport"] = borrowed_transport

        async with httpx.AsyncClient(**client_options) as client:
            while True:
                if page_count >= self._limits.max_pages:
                    raise InstrumentReferenceError(_LIMIT_EXCEEDED)
                remaining_deadline = deadline - _monotonic_time()
                if remaining_deadline <= 0:
                    raise InstrumentReferenceError(_LIMIT_EXCEEDED)
                remaining_bytes = self._limits.max_total_bytes - total_bytes
                if remaining_bytes <= 0:
                    raise InstrumentReferenceError(_LIMIT_EXCEEDED)

                if next_cursor is not None:
                    if pinned is None:
                        raise InstrumentReferenceError(_PROTOCOL_INVALID)
                    request_params = {
                        "snapshot_id": _required_string(pinned.get("snapshot_id")),
                        "cursor": next_cursor,
                    }
                page_budget = min(self._limits.max_response_bytes, remaining_bytes)
                request_budget = min(self._limits.request_timeout_seconds, remaining_deadline)
                try:
                    page, consumed = await asyncio.wait_for(
                        _get_json_page(
                            client,
                            path,
                            params=request_params,
                            max_bytes=page_budget,
                        ),
                        timeout=request_budget,
                    )
                except InstrumentReferenceError:
                    raise
                except asyncio.CancelledError:
                    raise
                except asyncio.TimeoutError:
                    if request_budget >= remaining_deadline:
                        raise InstrumentReferenceError(_LIMIT_EXCEEDED) from None
                    raise InstrumentReferenceError(_UNAVAILABLE) from None
                except Exception:
                    raise InstrumentReferenceError(_UNAVAILABLE) from None

                total_bytes += consumed
                try:
                    page_snapshot = _validate_page_metadata(
                        page,
                        config=self._config,
                        limits=self._limits,
                        now=_clock_now(self._clock),
                    )
                    if pinned is None:
                        pinned = page_snapshot
                        if _required_integer(pinned.get("record_count")) > self._limits.max_rows:
                            raise InstrumentReferenceError(_LIMIT_EXCEEDED)
                    elif _canonical_json(page_snapshot) != _canonical_json(pinned):
                        raise InstrumentReferenceError(_PROTOCOL_INVALID)
                    if pinned is None:
                        raise InstrumentReferenceError(_PROTOCOL_INVALID)
                    active_pins = pinned

                    page_rows = _validate_page_rows(
                        page,
                        config=self._config,
                        sequence=_required_integer(active_pins.get("sequence")),
                        publication_id=_required_string(active_pins.get("publication_id")),
                        previous_business_key=previous_business_key,
                        deadline=deadline,
                    )
                    if len(rows) + len(page_rows) > self._limits.max_rows:
                        raise InstrumentReferenceError(_LIMIT_EXCEEDED)
                    if len(rows) + len(page_rows) > _required_integer(
                        active_pins.get("record_count")
                    ):
                        raise InstrumentReferenceError(_PROTOCOL_INVALID)
                    if page_rows:
                        previous_business_key = _canonical_identity_key(
                            str(page_rows[-1]["business_key"])
                        )
                    rows.extend(page_rows)
                except InstrumentReferenceError:
                    raise
                except Exception:
                    raise InstrumentReferenceError(_PROTOCOL_INVALID) from None
                page_count += 1

                has_more = _required_boolean(page.get("has_more"))
                cursor = _optional_string(page.get("next_cursor"))
                if has_more is False:
                    if (
                        pinned is None
                        or cursor is not None
                        or len(rows) != _required_integer(pinned.get("record_count"))
                    ):
                        raise InstrumentReferenceError(_PROTOCOL_INVALID)
                    break
                if cursor is None or cursor in seen_cursors or pinned is None:
                    raise InstrumentReferenceError(_PROTOCOL_INVALID)
                if len(rows) >= _required_integer(pinned.get("record_count")):
                    raise InstrumentReferenceError(_PROTOCOL_INVALID)
                seen_cursors.add(cursor)
                next_cursor = cursor
                # Cursor is the only continuation token; page_size remains pinned
                # in the snapshot and must not be reinterpreted by later requests.
                now = _clock_now(self._clock)
                if now >= _parse_datetime(str(pinned["expires_at"])):
                    raise InstrumentReferenceError(_PROTOCOL_INVALID)

        if pinned is None or len(rows) != _required_integer(pinned.get("record_count")):
            raise InstrumentReferenceError(_PROTOCOL_INVALID)
        _validate_registry(rows, dataset_id=self._config.dataset_id, deadline=deadline)
        _ensure_deadline(deadline)
        _ensure_snapshot_fresh(pinned, clock=self._clock)
        result = _build_options(
            rows,
            pinned,
            search=search,
            limit=limit,
            effective_on=effective_on,
            deadline=deadline,
        )
        # asyncio.wait_for cannot run its timeout callback while synchronous
        # validation/search code occupies the event loop; recheck both budgets.
        _ensure_deadline(deadline)
        _ensure_snapshot_fresh(pinned, clock=self._clock)
        return result


def _monotonic_time() -> float:
    return asyncio.get_running_loop().time()


def _ensure_deadline(deadline: float) -> None:
    if _monotonic_time() >= deadline:
        raise InstrumentReferenceError(_LIMIT_EXCEEDED)


def _ensure_snapshot_fresh(
    pinned: Mapping[str, JsonValue], *, clock: Callable[[], datetime]
) -> None:
    if _clock_now(clock) >= _parse_datetime(str(pinned["expires_at"])):
        raise InstrumentReferenceError(_PROTOCOL_INVALID)


def _validate_origin(base_url: object) -> str:
    if not isinstance(base_url, str) or not base_url or base_url != base_url.strip():
        raise InstrumentReferenceError(_CONFIG_INVALID)
    try:
        parts = urlsplit(base_url)
        hostname = parts.hostname
        port = parts.port
    except ValueError:
        raise InstrumentReferenceError(_CONFIG_INVALID) from None
    if (
        parts.scheme not in {"https", "http"}
        or hostname is None
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
        or "?" in base_url
        or "#" in base_url
        or parts.path not in {"", "/"}
    ):
        raise InstrumentReferenceError(_CONFIG_INVALID)
    if parts.scheme == "http":
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            raise InstrumentReferenceError(_CONFIG_INVALID) from None
        if not address.is_loopback:
            raise InstrumentReferenceError(_CONFIG_INVALID)
    if port is not None and not 1 <= port <= 65535:
        raise InstrumentReferenceError(_CONFIG_INVALID)
    return f"{parts.scheme}://{parts.netloc}"


def _valid_identifier(value: object) -> bool:
    return isinstance(value, str) and _IDENTIFIER.fullmatch(value) is not None


def _valid_evidence(value: object) -> bool:
    return isinstance(value, str) and _EVIDENCE_ID.fullmatch(value) is not None


def _valid_cursor(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and len(value) <= 4096
        and value == value.strip()
        and not any(unicodedata.category(character) == "Cc" for character in value)
    )


def _required_integer(value: object) -> int:
    if type(value) is not int:
        raise InstrumentReferenceError(_PROTOCOL_INVALID)
    return value


def _required_string(value: object) -> str:
    if not isinstance(value, str):
        raise InstrumentReferenceError(_PROTOCOL_INVALID)
    return value


def _required_boolean(value: object) -> bool:
    if type(value) is not bool:
        raise InstrumentReferenceError(_PROTOCOL_INVALID)
    return value


def _optional_string(value: object) -> str | None:
    if value is not None and not isinstance(value, str):
        raise InstrumentReferenceError(_PROTOCOL_INVALID)
    return value


def _valid_text(value: object, *, maximum: int) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and len(value) <= maximum
        and not any(unicodedata.category(character) == "Cc" for character in value)
    )


def _validate_query(
    search: object,
    limit: object,
    effective_on: object,
    limits: InstrumentReferenceLimits,
) -> None:
    if (
        not isinstance(search, str)
        or len(search) > _MAX_SEARCH_CHARS
        or any(unicodedata.category(character) == "Cc" for character in search)
        or search != search.strip()
    ):
        raise InstrumentReferenceError(_CONFIG_INVALID)
    if type(limit) is not int or not 1 <= limit <= limits.ui_limit_max:
        raise InstrumentReferenceError(_CONFIG_INVALID)
    if effective_on is not None and (
        isinstance(effective_on, datetime) or not isinstance(effective_on, date)
    ):
        raise InstrumentReferenceError(_CONFIG_INVALID)


def _clock_now(clock: Callable[[], datetime]) -> datetime:
    try:
        value = clock()
    except Exception:
        raise InstrumentReferenceError(_CONFIG_INVALID) from None
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise InstrumentReferenceError(_CONFIG_INVALID)
    return value.astimezone(timezone.utc)


def _canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError):
        raise InstrumentReferenceError(_PROTOCOL_INVALID) from None


def _duplicate_rejecting_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_json_constant(_: str) -> None:
    raise ValueError("non-finite JSON number")


async def _get_json_page(
    client: httpx.AsyncClient,
    path: str,
    *,
    params: Mapping[str, str | int],
    max_bytes: int,
) -> tuple[dict[str, JsonValue], int]:
    body = bytearray()
    try:
        async with client.stream("GET", path, params=params) as response:
            if response.status_code == 429:
                raise InstrumentReferenceError(_RATE_LIMITED)
            if not 200 <= response.status_code < 300:
                raise InstrumentReferenceError(_UNAVAILABLE)
            content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if content_type != "application/json" and not content_type.endswith("+json"):
                raise InstrumentReferenceError(_PROTOCOL_INVALID)
            content_length = response.headers.get("content-length")
            if content_length is not None:
                if not content_length.isascii() or not content_length.isdigit():
                    raise InstrumentReferenceError(_PROTOCOL_INVALID)
                if int(content_length) > max_bytes:
                    raise InstrumentReferenceError(_LIMIT_EXCEEDED)
            content_encoding = response.headers.get("content-encoding", "identity")
            if content_encoding.strip().lower() != "identity":
                raise InstrumentReferenceError(_PROTOCOL_INVALID)
            async for chunk in response.aiter_raw():
                if len(body) + len(chunk) > max_bytes:
                    raise InstrumentReferenceError(_LIMIT_EXCEEDED)
                body.extend(chunk)
    except InstrumentReferenceError:
        raise
    except asyncio.CancelledError:
        raise
    except Exception:
        raise InstrumentReferenceError(_UNAVAILABLE) from None
    if not body:
        raise InstrumentReferenceError(_PROTOCOL_INVALID)
    try:
        decoded = json.loads(
            body.decode("utf-8", errors="strict"),
            object_pairs_hook=_duplicate_rejecting_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError):
        raise InstrumentReferenceError(_PROTOCOL_INVALID) from None
    if not isinstance(decoded, dict):
        raise InstrumentReferenceError(_PROTOCOL_INVALID)
    return decoded, len(body)


def _validate_page_metadata(
    page: dict[str, JsonValue],
    *,
    config: InstrumentReferenceConfig,
    limits: InstrumentReferenceLimits,
    now: datetime,
) -> dict[str, JsonValue]:
    if set(page) != _PAGE_KEYS:
        raise InstrumentReferenceError(_PROTOCOL_INVALID)
    snapshot = page.get("meta")
    if not isinstance(snapshot, dict) or set(snapshot) != {
        "snapshot",
        "ordering_fields",
        "storage_order",
        "identity_key_encoding",
    }:
        raise InstrumentReferenceError(_PROTOCOL_INVALID)
    snapshot_meta = snapshot.get("snapshot")
    if not isinstance(snapshot_meta, dict):
        raise InstrumentReferenceError(_PROTOCOL_INVALID)
    top_meta = {
        key: value
        for key, value in page.items()
        if key not in {"meta", "rows", "count", "next_cursor", "has_more"}
    }
    if _canonical_json(snapshot_meta) != _canonical_json(top_meta):
        raise InstrumentReferenceError(_PROTOCOL_INVALID)

    if (
        page["dataset_id"] != config.dataset_id
        or page["schema_version"] != _SCHEMA_VERSION
        or page["semantic_version"] != _SEMANTIC_VERSION
        or page["asset_class"] != "equity"
        or page["frequency"] != "irregular"
        or page["record_kind"] != "table"
        or page["filter_fields"] != []
        or page["time_field"] is not None
        or page["temporal_semantics"] != "none"
        or page["source_available_at_field"] is not None
        or page["calendar_id"] is not None
        or page["timezone"] != "Asia/Shanghai"
        or page["pit_policy"] != "unsupported"
        or page["business_key_fields"] != ["instrument_id"]
        or page["ordering_fields"] != ["instrument_id"]
        or page["identity_key_encoding"] != "canonical-json-array-v1"
        or _canonical_json(page["identity_semantics"]) != _canonical_json(_IDENTITY_SEMANTICS)
        or _canonical_json(page["storage_order"]) != _canonical_json(_STORAGE_ORDER)
        or snapshot["ordering_fields"] != ["instrument_id"]
        or _canonical_json(snapshot["storage_order"]) != _canonical_json(_STORAGE_ORDER)
        or snapshot["identity_key_encoding"] != "canonical-json-array-v1"
        or _canonical_json(page["window"])
        != _canonical_json({"start": None, "end": None, "end_exclusive": True})
        or page["adjustment_basis"] != "not_applicable"
        or page["currency"] is not None
        or _canonical_json(page["field_units"]) != b"{}"
        or _canonical_json(page["field_currencies"]) != b"{}"
        or _canonical_json(page["field_adjustments"]) != b"{}"
        or _canonical_json(page["schema"]) != _canonical_json(_schema_as_json())
    ):
        raise InstrumentReferenceError(_PROTOCOL_INVALID)

    source = page.get("source")
    if (
        not isinstance(source, dict)
        or set(source) != {"source_id", "source"}
        or source.get("source_id") != config.source_id
        or not _valid_text(source.get("source"), maximum=128)
        or str(source.get("source", "")).strip() == ""
    ):
        raise InstrumentReferenceError(_PROTOCOL_INVALID)
    contract = _contract_from_page(page, source)
    if (
        page.get("contract_sha256") != config.contract_sha256
        or _SHA256.fullmatch(str(page.get("contract_sha256"))) is None
        or hashlib.sha256(_canonical_json(contract)).hexdigest() != config.contract_sha256
    ):
        raise InstrumentReferenceError(_PROTOCOL_INVALID)

    quality = page.get("quality")
    if (
        not isinstance(quality, dict)
        or set(quality) != {"status", "report_id", "issue_count"}
        or quality.get("status") != "passed"
        or not _valid_identifier(quality.get("report_id"))
        or type(quality.get("issue_count")) is not int
        or quality.get("issue_count") != 0
    ):
        raise InstrumentReferenceError(_PROTOCOL_INVALID)

    for name in ("publication_id", "snapshot_id"):
        if not _valid_identifier(page.get(name)):
            raise InstrumentReferenceError(_PROTOCOL_INVALID)
    sequence = page.get("sequence")
    if type(sequence) is not int or sequence < 1:
        raise InstrumentReferenceError(_PROTOCOL_INVALID)
    if type(page.get("page_size")) is not int or page["page_size"] != limits.page_size:
        raise InstrumentReferenceError(_PROTOCOL_INVALID)
    record_count = page.get("record_count")
    if type(record_count) is not int or record_count < 0:
        raise InstrumentReferenceError(_PROTOCOL_INVALID)
    if record_count > limits.max_rows:
        raise InstrumentReferenceError(_LIMIT_EXCEEDED)
    for name in ("selection_sha256", "content_sha256"):
        value = page.get(name)
        if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
            raise InstrumentReferenceError(_PROTOCOL_INVALID)
    as_of = _parse_datetime(page.get("as_of"))
    created_at = _parse_datetime(page.get("created_at"))
    expires_at = _parse_datetime(page.get("expires_at"))
    if (
        as_of > created_at
        or as_of > now
        or created_at > now
        or expires_at <= now
        or expires_at <= created_at
    ):
        raise InstrumentReferenceError(_PROTOCOL_INVALID)
    if not _valid_date_only_or_none(page.get("as_of"), allow_datetime=True):
        raise InstrumentReferenceError(_PROTOCOL_INVALID)
    page_rows = page.get("rows")
    count = page.get("count")
    has_more = page.get("has_more")
    cursor = page.get("next_cursor")
    if (
        not isinstance(page_rows, list)
        or type(count) is not int
        or count != len(page_rows)
        or count < 0
        or count > limits.page_size
        or type(has_more) is not bool
    ):
        raise InstrumentReferenceError(_PROTOCOL_INVALID)
    if has_more:
        if count != limits.page_size or not _valid_cursor(cursor):
            raise InstrumentReferenceError(_PROTOCOL_INVALID)
    elif cursor is not None:
        raise InstrumentReferenceError(_PROTOCOL_INVALID)
    return snapshot_meta


def _schema_as_json() -> list[dict[str, JsonValue]]:
    return [
        {"name": name, "data_type": data_type, "nullable": nullable}
        for name, data_type, nullable in _SCHEMA
    ]


def _contract_from_page(
    page: Mapping[str, JsonValue], source: Mapping[str, JsonValue]
) -> dict[str, JsonValue]:
    return {
        "dataset_id": page["dataset_id"],
        "schema_version": page["schema_version"],
        "semantic_version": page["semantic_version"],
        "asset_class": page["asset_class"],
        "frequency": page["frequency"],
        "record_kind": page["record_kind"],
        "fields": page["schema"],
        "business_key": page["business_key_fields"],
        "ordering": page["ordering_fields"],
        "filter_fields": page["filter_fields"],
        "time_field": page["time_field"],
        "temporal_semantics": page["temporal_semantics"],
        "source_available_at_field": page["source_available_at_field"],
        "source": {"source_id": source["source_id"], "source": source["source"]},
        "field_units": page["field_units"],
        "field_currencies": page["field_currencies"],
        "currency": page["currency"],
        "adjustment_basis": page["adjustment_basis"],
        "field_adjustments": page["field_adjustments"],
        "calendar_id": page["calendar_id"],
        "timezone": page["timezone"],
        "pit_policy": page["pit_policy"],
    }


def _valid_date_only_or_none(value: object, *, allow_datetime: bool = False) -> bool:
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    if allow_datetime:
        try:
            _parse_datetime(value)
            return True
        except InstrumentReferenceError:
            return False
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return False
    return parsed.isoformat() == value


def _parse_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise InstrumentReferenceError(_PROTOCOL_INVALID)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise InstrumentReferenceError(_PROTOCOL_INVALID) from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise InstrumentReferenceError(_PROTOCOL_INVALID)
    return parsed.astimezone(timezone.utc)


def _canonical_identity_key(value: str) -> bytes:
    try:
        decoded = json.loads(value)
    except (json.JSONDecodeError, ValueError):
        raise InstrumentReferenceError(_PROTOCOL_INVALID) from None
    if (
        not isinstance(decoded, list)
        or len(decoded) != 1
        or not _valid_identifier(decoded[0])
        or json.dumps(decoded, ensure_ascii=False, separators=(",", ":")) != value
    ):
        raise InstrumentReferenceError(_PROTOCOL_INVALID)
    return value.encode("ascii")


def _validate_page_rows(
    page: Mapping[str, JsonValue],
    *,
    config: InstrumentReferenceConfig,
    sequence: int,
    publication_id: str,
    previous_business_key: bytes | None,
    deadline: float,
) -> list[dict[str, JsonValue]]:
    raw_rows = page.get("rows")
    if not isinstance(raw_rows, list):
        raise InstrumentReferenceError(_PROTOCOL_INVALID)
    validated: list[dict[str, JsonValue]] = []
    prev = previous_business_key
    for raw in raw_rows:
        _ensure_deadline(deadline)
        if not isinstance(raw, dict) or set(raw) != _ROW_KEYS:
            raise InstrumentReferenceError(_PROTOCOL_INVALID)
        row = raw
        publication_sequence = row.get("publication_sequence")
        revision = row.get("revision")
        if (
            row.get("dataset_id") != config.dataset_id
            or row.get("business_date") is not None
            or row.get("publication_id") != publication_id
            or type(publication_sequence) is not int
            or publication_sequence != sequence
            or type(revision) is not int
            or revision < 1
        ):
            raise InstrumentReferenceError(_PROTOCOL_INVALID)
        for name in ("event_at", "observed_at", "source_published_at", "available_at"):
            value = row.get(name)
            if value is not None:
                _parse_datetime(value)
        payload = row.get("payload")
        if not isinstance(payload, dict) or set(payload) != _PAYLOAD_KEYS:
            raise InstrumentReferenceError(_PROTOCOL_INVALID)
        _validate_payload(payload)
        instrument_id = str(payload["instrument_id"])
        expected_key = json.dumps([instrument_id], ensure_ascii=False, separators=(",", ":"))
        if row.get("business_key") != expected_key:
            raise InstrumentReferenceError(_PROTOCOL_INVALID)
        key_bytes = _canonical_identity_key(expected_key)
        if prev is not None and key_bytes <= prev:
            raise InstrumentReferenceError(_PROTOCOL_INVALID)
        prev = key_bytes
        record_hash = row.get("record_hash")
        if not isinstance(record_hash, str) or _SHA256.fullmatch(record_hash) is None:
            raise InstrumentReferenceError(_PROTOCOL_INVALID)
        row_body = {
            "business_key": row["business_key"],
            "business_date": None,
            "event_at": row["event_at"],
            "observed_at": row["observed_at"],
            "source_published_at": row["source_published_at"],
            "available_at": row["available_at"],
            "payload": payload,
        }
        if hashlib.sha256(_canonical_json(row_body)).hexdigest() != record_hash:
            raise InstrumentReferenceError(_PROTOCOL_INVALID)
        validated.append(row)
    return validated


def _validate_payload(payload: Mapping[str, JsonValue]) -> None:
    if (
        payload.get("profile_version") != _PROFILE_VERSION
        or not _valid_identifier(payload.get("registry_version"))
        or not _valid_evidence(payload.get("registry_evidence_ref"))
        or not _valid_identifier(payload.get("instrument_id"))
        or payload.get("asset_type") != "stock"
        or not isinstance(payload.get("symbol"), str)
        or _SYMBOL.fullmatch(str(payload.get("symbol"))) is None
        or payload.get("market") != "CN"
        or not isinstance(payload.get("exchange"), str)
        or payload.get("exchange") not in {"XSHG", "XSHE", "XBSE"}
        or not _valid_text(payload.get("name"), maximum=128)
        or str(payload.get("name", "")).strip() == ""
        or not _valid_identifier(payload.get("lifecycle_version"))
        or not isinstance(payload.get("status"), str)
        or payload.get("status") not in {"active", "delisted", "unknown"}
        or not isinstance(payload.get("status_as_of"), str)
        or not _valid_date_only_or_none(payload.get("status_as_of"))
        or not _valid_evidence(payload.get("status_evidence_ref"))
        or type(payload.get("start_boundary_unknown")) is not bool
    ):
        raise InstrumentReferenceError(_PROTOCOL_INVALID)
    status_as_of = date.fromisoformat(str(payload["status_as_of"]))
    known_start = payload.get("known_start_date")
    delisted_on = payload.get("delisted_on")
    start_evidence = payload.get("start_evidence_ref")
    delist_evidence = payload.get("delist_evidence_ref")
    if known_start is not None and not _valid_date_only_or_none(known_start):
        raise InstrumentReferenceError(_PROTOCOL_INVALID)
    if delisted_on is not None and not _valid_date_only_or_none(delisted_on):
        raise InstrumentReferenceError(_PROTOCOL_INVALID)
    if start_evidence is not None and not _valid_evidence(start_evidence):
        raise InstrumentReferenceError(_PROTOCOL_INVALID)
    if delist_evidence is not None and not _valid_evidence(delist_evidence):
        raise InstrumentReferenceError(_PROTOCOL_INVALID)
    if payload["start_boundary_unknown"]:
        if known_start is not None or start_evidence is not None:
            raise InstrumentReferenceError(_PROTOCOL_INVALID)
    elif known_start is None or start_evidence is None:
        raise InstrumentReferenceError(_PROTOCOL_INVALID)
    if payload["status"] == "delisted":
        if delisted_on is None or delist_evidence is None:
            raise InstrumentReferenceError(_PROTOCOL_INVALID)
        if status_as_of < date.fromisoformat(str(delisted_on)):
            raise InstrumentReferenceError(_PROTOCOL_INVALID)
    elif delisted_on is not None or delist_evidence is not None:
        raise InstrumentReferenceError(_PROTOCOL_INVALID)
    if known_start is not None and delisted_on is not None:
        if date.fromisoformat(str(known_start)) > date.fromisoformat(str(delisted_on)):
            raise InstrumentReferenceError(_PROTOCOL_INVALID)
    aliases = payload.get("aliases")
    if not isinstance(aliases, list) or len(aliases) > 16:
        raise InstrumentReferenceError(_PROTOCOL_INVALID)
    for alias in aliases:
        if not isinstance(alias, dict) or set(alias) != _ALIAS_KEYS:
            raise InstrumentReferenceError(_PROTOCOL_INVALID)
        if any(
            not _valid_identifier(alias.get(field)) for field in ("alias", "alias_version")
        ) or not _valid_evidence(alias.get("evidence_ref")):
            raise InstrumentReferenceError(_PROTOCOL_INVALID)
        valid_from = alias.get("valid_from")
        valid_through = alias.get("valid_through")
        if valid_from is not None and not _valid_date_only_or_none(valid_from):
            raise InstrumentReferenceError(_PROTOCOL_INVALID)
        if valid_through is not None and not _valid_date_only_or_none(valid_through):
            raise InstrumentReferenceError(_PROTOCOL_INVALID)
        if valid_from is not None and valid_through is not None:
            if date.fromisoformat(str(valid_from)) > date.fromisoformat(str(valid_through)):
                raise InstrumentReferenceError(_PROTOCOL_INVALID)


def _validate_registry(
    rows: list[dict[str, JsonValue]], *, dataset_id: str, deadline: float
) -> None:
    instruments: dict[str, Mapping[str, JsonValue]] = {}
    symbols: dict[str, str] = {}
    alias_rows: dict[str, list[tuple[str, date | None, date | None]]] = {}
    registry_pins: set[tuple[str, str, str]] = set()
    for row in rows:
        _ensure_deadline(deadline)
        payload = row["payload"]
        if not isinstance(payload, dict):
            raise InstrumentReferenceError(_PROTOCOL_INVALID)
        instrument_id = str(payload["instrument_id"])
        symbol = str(payload["symbol"])
        if instrument_id in instruments or symbol in symbols:
            raise InstrumentReferenceError(_PROTOCOL_INVALID)
        instruments[instrument_id] = payload
        symbols[symbol] = instrument_id
        registry_pins.add(
            (
                str(payload["profile_version"]),
                str(payload["registry_version"]),
                str(payload["registry_evidence_ref"]),
            )
        )
        aliases = payload["aliases"]
        if not isinstance(aliases, list):
            raise InstrumentReferenceError(_PROTOCOL_INVALID)
        for alias in aliases:
            _ensure_deadline(deadline)
            if not isinstance(alias, dict):
                raise InstrumentReferenceError(_PROTOCOL_INVALID)
            alias_text = str(alias["alias"])
            if alias_text in instruments and alias_text != instrument_id:
                raise InstrumentReferenceError(_PROTOCOL_INVALID)
            start = date.fromisoformat(str(alias["valid_from"])) if alias["valid_from"] else None
            end = (
                date.fromisoformat(str(alias["valid_through"])) if alias["valid_through"] else None
            )
            alias_rows.setdefault(alias_text, []).append((instrument_id, start, end))
    if len(registry_pins) > 1:
        raise InstrumentReferenceError(_PROTOCOL_INVALID)
    for alias_text, intervals in alias_rows.items():
        _ensure_deadline(deadline)
        if alias_text in instruments and any(iid != alias_text for iid, _, _ in intervals):
            raise InstrumentReferenceError(_PROTOCOL_INVALID)
        symbol_owner = symbols.get(alias_text)
        if symbol_owner is not None and any(iid != symbol_owner for iid, _, _ in intervals):
            raise InstrumentReferenceError(_PROTOCOL_INVALID)
        ordered = sorted(intervals, key=lambda item: item[1] or date.min)
        max_end: date | None = None
        has_previous = False
        for _, start, end in ordered:
            _ensure_deadline(deadline)
            if has_previous and (max_end is None or start is None or max_end >= start):
                raise InstrumentReferenceError(_PROTOCOL_INVALID)
            if not has_previous or max_end is not None and (end is None or end > max_end):
                max_end = end
            has_previous = True
    # Every row has already been scoped to the pinned dataset and source metadata.
    if not dataset_id:
        raise InstrumentReferenceError(_PROTOCOL_INVALID)


def _build_options(
    rows: list[dict[str, JsonValue]],
    pinned: Mapping[str, JsonValue],
    *,
    search: str,
    limit: int,
    effective_on: date | None,
    deadline: float,
) -> dict[str, JsonValue]:
    query = search.casefold()
    matched: list[tuple[dict[str, JsonValue], dict[str, JsonValue] | None]] = []
    alias_only_without_date = False
    for row in rows:
        _ensure_deadline(deadline)
        payload = row["payload"]
        if not isinstance(payload, dict):
            raise InstrumentReferenceError(_PROTOCOL_INVALID)
        canonical_match = not query or any(
            query in str(payload[field]).casefold() for field in ("symbol", "name", "instrument_id")
        )
        aliases = payload["aliases"]
        if not isinstance(aliases, list):
            raise InstrumentReferenceError(_PROTOCOL_INVALID)
        exact_aliases = [
            alias
            for alias in aliases
            if isinstance(alias, dict) and str(alias["alias"]) == search and bool(query)
        ]
        if exact_aliases and effective_on is None and not canonical_match:
            alias_only_without_date = True
        valid_alias: dict[str, JsonValue] | None = None
        if effective_on is not None:
            for alias in exact_aliases:
                _ensure_deadline(deadline)
                if _alias_is_valid(alias, effective_on):
                    valid_alias = {
                        "alias": alias["alias"],
                        "alias_version": alias["alias_version"],
                        "evidence_ref": alias["evidence_ref"],
                        "valid_from": alias["valid_from"],
                        "valid_through": alias["valid_through"],
                    }
                    break
        if canonical_match or valid_alias is not None:
            matched.append((payload, valid_alias))
    if alias_only_without_date:
        raise InstrumentReferenceError(_EFFECTIVE_DATE_REQUIRED)
    matched.sort(key=lambda item: (str(item[0]["symbol"]), str(item[0]["instrument_id"])))
    total = len(matched)
    items: list[JsonValue] = []
    for payload, matched_alias in matched[:limit]:
        item: dict[str, JsonValue] = {
            "asset_type": "stock",
            "symbol": payload["symbol"],
            "name": payload["name"],
            "market": "CN",
            "exchange": payload["exchange"],
            "instrument_id": payload["instrument_id"],
            "catalog_verified": True,
            "data_availability": "unknown",
            "has_snapshot": None,
            "has_history": None,
            "history_rows": None,
            "source_table": None,
            "latest_date": None,
            "lifecycle_status": payload["status"],
            "status_as_of": payload["status_as_of"],
        }
        if matched_alias is not None:
            item["matched_alias"] = matched_alias
        items.append(item)
    source = pinned.get("source")
    source_id: JsonValue = source.get("source_id") if isinstance(source, dict) else None
    provenance: dict[str, JsonValue] = {
        "source": "opendata_published_instrument_reference",
        "dataset_id": pinned["dataset_id"],
        "source_id": source_id,
        "publication_id": pinned["publication_id"],
        "snapshot_id": pinned["snapshot_id"],
        "sequence": pinned["sequence"],
        "schema_version": pinned["schema_version"],
        "semantic_version": pinned["semantic_version"],
        "contract_sha256": pinned["contract_sha256"],
        "content_sha256": pinned["content_sha256"],
        "selection_sha256": pinned["selection_sha256"],
        "as_of": pinned["as_of"],
        "expires_at": pinned["expires_at"],
        "registry_version": _registry_pin_value(rows, "registry_version"),
        "profile_version": _registry_pin_value(rows, "profile_version"),
        "coverage": "unknown",
    }
    return {
        "asset_type": "stock",
        "catalog_mode": "opendata",
        "complete": True,
        "has_more": total > limit,
        "total": total,
        "data_availability": "unknown",
        "items": items,
        "provenance": provenance,
    }


def _registry_pin_value(rows: list[dict[str, JsonValue]], key: str) -> JsonValue:
    if not rows:
        # Empty catalogs have no row-level registry evidence; metadata still pins
        # the profile/source contract, while no fabricated version is emitted.
        return None
    payload = rows[0].get("payload")
    if not isinstance(payload, dict):
        raise InstrumentReferenceError(_PROTOCOL_INVALID)
    return payload.get(key)


def _alias_is_valid(alias: Mapping[str, JsonValue], effective_on: date) -> bool:
    valid_from = alias.get("valid_from")
    valid_through = alias.get("valid_through")
    return (valid_from is None or effective_on >= date.fromisoformat(str(valid_from))) and (
        valid_through is None or effective_on <= date.fromisoformat(str(valid_through))
    )
