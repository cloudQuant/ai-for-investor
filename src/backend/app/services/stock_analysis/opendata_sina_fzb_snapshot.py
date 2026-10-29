"""Read one explicitly selected, source-native Sina FZB capture from OpenData.

This reader pins an existing publication and capture. It never discovers a
"latest" capture, makes upstream requests, converts financial values, or claims
historical completeness. The returned payload is OpenData's source-native
projection; it is not the original Sina response bytes.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from app.services.market_data.opendata_credentials import (
    OpendataCredentials,
    OpendataCredentialsError,
)

_DATASET_ID = "sina_fzb_report_observations"
_SOURCE = {"source": "sina", "source_id": "sina-fzb"}
_SCHEMA_FIELDS = (
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
_PAYLOAD_FIELDS = frozenset(name for name, _data_type in _SCHEMA_FIELDS)
_BUSINESS_FIELDS = ("instrument_id", "capture_id", "statement_code", "report_period")
_FILTER_FIELDS = ("instrument_id", "capture_id")
_TEMPORAL_FIELDS = {
    "business_date": "null for atemporal table records; not a historical business date",
    "observed_at": "source observation time",
    "source_published_at": "source publication time",
    "available_at": "platform availability time",
    "event_at": "source event time",
}
_STORAGE_ORDER = [
    {"field": "business_date", "direction": "asc", "nulls": "last", "comparison": "native"},
    {"field": "business_key", "direction": "asc", "comparison": "binary_lexicographic"},
]
_IDENTITY_SEMANTICS = {
    "version": 1,
    "business_key_fields": list(_BUSINESS_FIELDS),
    "identity_key_encoding": "canonical-json-array-v1",
    "revision": "latest non-deleted revision per business_key at the pinned publication sequence",
    "ordering_fields": list(_BUSINESS_FIELDS),
    "storage_order": _STORAGE_ORDER,
    "temporal_semantics": "none",
    "time_field": None,
    "temporal_fields": _TEMPORAL_FIELDS,
}
_SNAPSHOT_FIELDS = frozenset(
    {
        "snapshot_id",
        "dataset_id",
        "publication_id",
        "sequence",
        "schema_version",
        "semantic_version",
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
        "business_key_fields",
        "ordering_fields",
        "storage_order",
        "identity_key_encoding",
        "filter_fields",
        "time_field",
        "temporal_semantics",
        "timezone",
        "pit_policy",
        "source_available_at_field",
        "calendar_id",
        "contract_sha256",
        "window",
        "page_size",
        "as_of",
        "created_at",
        "expires_at",
        "record_count",
        "selection_sha256",
        "content_sha256",
        "identity_semantics",
        "selection",
    }
)
_ROW_FIELDS = frozenset(
    {
        "dataset_id",
        "business_key",
        "revision",
        "publication_id",
        "publication_sequence",
        "business_date",
        "event_at",
        "observed_at",
        "source_published_at",
        "available_at",
        "payload",
        "record_hash",
    }
)
_PAGE_FIELDS = frozenset({"rows", "count", "next_cursor", "has_more", "meta"})
_META_FIELDS = frozenset({"snapshot", "ordering_fields", "storage_order", "identity_key_encoding"})
_INSTRUMENT_ID = re.compile(r"[0-9]{6}\.(?:SH|SZ)\Z", re.ASCII)
_PUBLICATION_ID = re.compile(r"[0-9a-f]{32}\Z", re.ASCII)
_CAPTURE_ID = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_SHA256 = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_OPAQUE_ID = re.compile(r"[0-9a-f]{32}\Z", re.ASCII)
_ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z", re.ASCII)
_ROW_PAGE_SIZE = 30
_MAX_PAGES = 9
_MAX_ROWS = 256
_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
_MAX_TOTAL_RESPONSE_BYTES = 64 * 1024 * 1024
_MAX_RECORD_BYTES = 256 * 1024
_MAX_CURSOR_LENGTH = 8_192
_STREAM_CHUNK_BYTES = 64 * 1024
_MAX_JSON_DEPTH = 32
_MAX_JSON_NODES = 1_000_000
_MAX_REPORT_ENTRIES = 512
_MAX_CAPTURE_OCCURRENCES = 131_072
_REQUEST_TIMEOUT_SECONDS = 8.0
_TOTAL_TIMEOUT_SECONDS = 60.0
_SAFE_CONFIGURATION_ERRORS = frozenset(
    {
        "OPENDATA_CREDENTIAL_INVALID",
        "OPENDATA_BASE_URL_INVALID",
        "allowed_hosts_invalid",
        "configuration_invalid",
    }
)


class OpenDataSinaFzbSnapshotError(RuntimeError):
    """Stable failure code that never includes credentials, URLs, or response bodies."""

    def __init__(self, code: str, *, status_code: int | None = None) -> None:
        self.code = code
        self.status_code = status_code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class SinaFzbSnapshotResult:
    """One fully fetched pinned capture, retained as raw OpenData row envelopes."""

    snapshot: dict[str, Any]
    records: tuple[dict[str, Any], ...]
    page_count: int
    response_bytes: int
    completeness: str = "unknown"
    historical_as_of_status: str = "unavailable"
    eligible_for_decision_or_backtest: bool = False


class OpenDataSinaFzbSnapshotReader:
    """Fetch pages from one exact publication/instrument/capture selector.

    ``transport`` is an injection seam for deterministic mock tests. When the
    reader creates its HTTP client it disables environment proxies and follows
    no redirects. Non-loopback endpoints require HTTPS and an exact host:port
    allowlist. No operation falls back to AkShare or to an automatically found
    capture.
    """

    def __init__(
        self,
        credentials: OpendataCredentials | None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        configuration_error: str | None = None,
        allowed_hosts: str | set[str] | frozenset[str] | None = None,
    ) -> None:
        self._credentials = credentials
        self._transport = transport
        self._configuration_error = _safe_configuration_error(configuration_error)
        if allowed_hosts is None:
            self._allowed_origins = frozenset()
        elif isinstance(allowed_hosts, str):
            self._allowed_origins, error = _parse_allowed_origins(
                entry for entry in allowed_hosts.split(",") if entry.strip()
            )
            self._configuration_error = self._configuration_error or error
        elif isinstance(allowed_hosts, (set, frozenset)):
            if any(type(host) is not str for host in allowed_hosts):
                raise ValueError("allowed hosts must contain only strings")
            self._allowed_origins, error = _parse_allowed_origins(
                entry for entry in allowed_hosts if entry.strip()
            )
            self._configuration_error = self._configuration_error or error
        else:
            raise ValueError("allowed hosts must be a string or a set of strings")

    @classmethod
    def from_environment(
        cls,
        *,
        allowed_hosts: str | set[str] | frozenset[str] | None = None,
    ) -> OpenDataSinaFzbSnapshotReader:
        """Resolve the shared OpenData credential reference without exposing it."""
        import os

        if allowed_hosts is None:
            allowed_hosts = os.environ.get("STOCK_ANALYSIS_OPENDATA_SINA_FZB_ALLOWED_HOSTS", "")
        try:
            credentials = OpendataCredentials.from_environment()
        except OpendataCredentialsError as exc:
            return cls(None, configuration_error=exc.code, allowed_hosts=allowed_hosts)
        return cls(credentials, allowed_hosts=allowed_hosts)

    async def fetch_capture(
        self,
        *,
        instrument_id: str,
        publication_id: str,
        capture_id: str,
    ) -> SinaFzbSnapshotResult:
        """Read exactly one explicitly named capture and fail without partial rows."""
        _validate_request_identity(
            instrument_id=instrument_id,
            publication_id=publication_id,
            capture_id=capture_id,
        )
        endpoint = self._endpoint_url()
        if self._configuration_error is not None:
            raise OpenDataSinaFzbSnapshotError(self._configuration_error)
        if self._credentials is None:
            raise OpenDataSinaFzbSnapshotError("credential_missing")

        started_at = asyncio.get_running_loop().time()
        total_bytes = 0
        request_body = {
            "dataset_id": _DATASET_ID,
            "publication_id": publication_id,
            "page_size": _ROW_PAGE_SIZE,
            "instrument_id": instrument_id,
            "capture_id": capture_id,
        }
        async with httpx.AsyncClient(
            transport=self._transport,
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(_REQUEST_TIMEOUT_SECONDS),
        ) as client:
            snapshot, response_bytes = await self._request_json(
                client,
                "POST",
                f"{endpoint}/api/v2/snapshots",
                started_at=started_at,
                json_body=request_body,
                expected_status=201,
                max_response_bytes=_MAX_TOTAL_RESPONSE_BYTES,
            )
            _validate_snapshot(
                snapshot,
                instrument_id=instrument_id,
                publication_id=publication_id,
                capture_id=capture_id,
            )
            total_bytes += response_bytes
            if total_bytes > _MAX_TOTAL_RESPONSE_BYTES:
                raise OpenDataSinaFzbSnapshotError("total_response_too_large")

            snapshot_id = snapshot["snapshot_id"]
            record_count = snapshot["record_count"]
            if record_count > _MAX_ROWS:
                raise OpenDataSinaFzbSnapshotError("snapshot_row_limit_exceeded")

            rows: list[dict[str, Any]] = []
            seen_business_keys: set[str] = set()
            seen_cursors: set[str] = set()
            previous_business_key: str | None = None
            total_occurrences = 0
            cursor: str | None = None
            page_count = 0
            while True:
                self._check_deadline(started_at)
                if page_count >= _MAX_PAGES:
                    raise OpenDataSinaFzbSnapshotError("snapshot_page_limit_exceeded")
                params: dict[str, str] = {"snapshot_id": snapshot_id}
                if cursor is not None:
                    params["cursor"] = cursor
                page, page_bytes = await self._request_json(
                    client,
                    "GET",
                    f"{endpoint}/api/v2/datasets/{quote(_DATASET_ID, safe='')}/records",
                    started_at=started_at,
                    params=params,
                    expected_status=200,
                    max_response_bytes=_MAX_TOTAL_RESPONSE_BYTES - total_bytes,
                )
                total_bytes += page_bytes
                if total_bytes > _MAX_TOTAL_RESPONSE_BYTES:
                    raise OpenDataSinaFzbSnapshotError("total_response_too_large")
                page_count += 1
                page_rows, next_cursor, has_more, page_occurrences = _validate_page(
                    page,
                    snapshot=snapshot,
                    instrument_id=instrument_id,
                    capture_id=capture_id,
                )
                total_occurrences += page_occurrences
                if total_occurrences > _MAX_CAPTURE_OCCURRENCES:
                    raise OpenDataSinaFzbSnapshotError("capture_entry_limit_exceeded")
                for row in page_rows:
                    business_key = row["business_key"]
                    if business_key in seen_business_keys:
                        raise OpenDataSinaFzbSnapshotError("duplicate_business_key")
                    if previous_business_key is not None and business_key <= previous_business_key:
                        raise OpenDataSinaFzbSnapshotError("record_order_invalid")
                    encoded_row = _canonical_json_bytes(row)
                    if len(encoded_row) > _MAX_RECORD_BYTES:
                        raise OpenDataSinaFzbSnapshotError("record_too_large")
                    seen_business_keys.add(business_key)
                    previous_business_key = business_key
                    rows.append(row)
                    if len(rows) > _MAX_ROWS:
                        raise OpenDataSinaFzbSnapshotError("snapshot_row_limit_exceeded")
                if not has_more:
                    break
                assert next_cursor is not None
                if next_cursor in seen_cursors or next_cursor == cursor:
                    raise OpenDataSinaFzbSnapshotError("snapshot_cursor_repeated")
                seen_cursors.add(next_cursor)
                cursor = next_cursor

        self._check_deadline(started_at)
        if len(rows) != record_count:
            raise OpenDataSinaFzbSnapshotError("snapshot_incomplete")
        if page_count < 1:
            raise OpenDataSinaFzbSnapshotError("snapshot_incomplete")
        return SinaFzbSnapshotResult(
            snapshot=snapshot,
            records=tuple(rows),
            page_count=page_count,
            response_bytes=total_bytes,
        )

    async def _request_json(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        *,
        started_at: float,
        params: Mapping[str, str] | None = None,
        json_body: Mapping[str, Any] | None = None,
        expected_status: int,
        max_response_bytes: int,
    ) -> tuple[dict[str, Any], int]:
        if self._configuration_error is not None:
            raise OpenDataSinaFzbSnapshotError(self._configuration_error)
        if self._credentials is None:
            raise OpenDataSinaFzbSnapshotError("credential_missing")
        if max_response_bytes <= 0:
            raise OpenDataSinaFzbSnapshotError("total_response_too_large")
        remaining = self._remaining_seconds(started_at)
        response_limit = min(_MAX_RESPONSE_BYTES, max_response_bytes)

        async def read_body() -> bytearray:
            response_bytes = bytearray()
            async with client.stream(
                method,
                url,
                params=params,
                json=json_body,
                headers={
                    "X-API-Key": self._credentials.api_key,
                    "Accept": "application/json",
                },
                timeout=httpx.Timeout(min(_REQUEST_TIMEOUT_SECONDS, remaining)),
                follow_redirects=False,
            ) as response:
                if response.status_code != expected_status:
                    raise _http_error(response.status_code)
                if "application/json" not in response.headers.get("content-type", "").lower():
                    raise OpenDataSinaFzbSnapshotError("content_type_invalid")
                async for chunk in response.aiter_bytes(chunk_size=_STREAM_CHUNK_BYTES):
                    if len(response_bytes) + len(chunk) > response_limit:
                        raise OpenDataSinaFzbSnapshotError("response_too_large")
                    response_bytes.extend(chunk)
            return response_bytes

        try:
            response_bytes = await asyncio.wait_for(read_body(), timeout=remaining)
        except OpenDataSinaFzbSnapshotError:
            raise
        except (TimeoutError, asyncio.TimeoutError, httpx.TimeoutException):
            raise OpenDataSinaFzbSnapshotError("deadline_exceeded") from None
        except httpx.TransportError:
            raise OpenDataSinaFzbSnapshotError("transport_error") from None
        except Exception:
            raise OpenDataSinaFzbSnapshotError("response_read_failed") from None

        if self._credentials.api_key.encode("utf-8") in response_bytes:
            raise OpenDataSinaFzbSnapshotError("credential_reflected_in_response")
        try:
            payload = json.loads(
                response_bytes.decode("utf-8"),
                object_pairs_hook=_unique_object,
                parse_constant=_reject_json_constant,
            )
            if not isinstance(payload, dict):
                raise ValueError("response root is not an object")
            _validate_json_tree(payload)
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, TypeError, ValueError):
            raise OpenDataSinaFzbSnapshotError("response_json_invalid") from None
        if _json_contains_secret(payload, self._credentials.api_key):
            raise OpenDataSinaFzbSnapshotError("credential_reflected_in_response")
        return payload, len(response_bytes)

    def _endpoint_url(self) -> str:
        if self._configuration_error is not None:
            raise OpenDataSinaFzbSnapshotError(self._configuration_error)
        if self._credentials is None:
            raise OpenDataSinaFzbSnapshotError("credential_missing")
        try:
            parsed = urlsplit(self._credentials.base_url)
            hostname = parsed.hostname
            configured_port = parsed.port
        except ValueError:
            raise OpenDataSinaFzbSnapshotError("base_url_invalid") from None
        if (
            parsed.scheme not in {"http", "https"}
            or not hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or configured_port == 0
        ):
            raise OpenDataSinaFzbSnapshotError("base_url_invalid")
        normalized_hostname = hostname.lower().rstrip(".")
        port = configured_port or (443 if parsed.scheme == "https" else 80)
        is_loopback = _is_loopback_host(normalized_hostname)
        if parsed.scheme == "http" and not is_loopback:
            raise OpenDataSinaFzbSnapshotError("base_url_insecure_transport")
        if not is_loopback and (normalized_hostname, port) not in self._allowed_origins:
            raise OpenDataSinaFzbSnapshotError("base_url_host_not_allowed")
        return self._credentials.base_url.rstrip("/")

    @staticmethod
    def _remaining_seconds(started_at: float) -> float:
        remaining = _TOTAL_TIMEOUT_SECONDS - (asyncio.get_running_loop().time() - started_at)
        if remaining <= 0:
            raise OpenDataSinaFzbSnapshotError("deadline_exceeded")
        return remaining

    @classmethod
    def _check_deadline(cls, started_at: float) -> None:
        cls._remaining_seconds(started_at)


def _validate_request_identity(
    *, instrument_id: object, publication_id: object, capture_id: object
) -> None:
    if type(instrument_id) is not str or _INSTRUMENT_ID.fullmatch(instrument_id) is None:
        raise OpenDataSinaFzbSnapshotError("instrument_id_invalid")
    if type(publication_id) is not str or _PUBLICATION_ID.fullmatch(publication_id) is None:
        raise OpenDataSinaFzbSnapshotError("publication_id_invalid")
    if type(capture_id) is not str or _CAPTURE_ID.fullmatch(capture_id) is None:
        raise OpenDataSinaFzbSnapshotError("capture_id_invalid")


def _validate_snapshot(
    snapshot: object,
    *,
    instrument_id: str,
    publication_id: str,
    capture_id: str,
) -> dict[str, Any]:
    if not isinstance(snapshot, dict) or set(snapshot) != _SNAPSHOT_FIELDS:
        raise OpenDataSinaFzbSnapshotError("snapshot_metadata_invalid")
    if (
        snapshot.get("snapshot_id") is None
        or type(snapshot.get("snapshot_id")) is not str
        or _OPAQUE_ID.fullmatch(snapshot["snapshot_id"]) is None
        or snapshot.get("dataset_id") != _DATASET_ID
        or snapshot.get("publication_id") != publication_id
        or _PUBLICATION_ID.fullmatch(snapshot.get("publication_id", "")) is None
    ):
        raise OpenDataSinaFzbSnapshotError("snapshot_scope_mismatch")
    if type(snapshot.get("sequence")) is not int or snapshot["sequence"] < 1:
        raise OpenDataSinaFzbSnapshotError("snapshot_metadata_invalid")
    if (
        snapshot.get("schema_version") != "source-native-report-v1"
        or snapshot.get("semantic_version") != "sina-fzb-source-native-v1"
        or snapshot.get("source") != _SOURCE
        or snapshot.get("schema")
        != [
            {"name": name, "data_type": data_type, "nullable": False}
            for name, data_type in _SCHEMA_FIELDS
        ]
    ):
        raise OpenDataSinaFzbSnapshotError("snapshot_contract_mismatch")
    if (
        snapshot.get("quality") != {"status": "unknown", "report_id": None, "issue_count": 0}
        or snapshot.get("field_units") != {"source_update_epoch_seconds": "unix_seconds"}
        or snapshot.get("field_currencies") != {}
        or snapshot.get("field_adjustments") != {}
        or snapshot.get("currency") is not None
        or snapshot.get("adjustment_basis") != "not_applicable"
        or snapshot.get("asset_class") != "equity"
        or snapshot.get("frequency") != "irregular"
        or snapshot.get("record_kind") != "table"
    ):
        raise OpenDataSinaFzbSnapshotError("snapshot_contract_mismatch")
    if (
        snapshot.get("business_key_fields") != list(_BUSINESS_FIELDS)
        or snapshot.get("ordering_fields") != list(_BUSINESS_FIELDS)
        or snapshot.get("filter_fields") != list(_FILTER_FIELDS)
        or snapshot.get("storage_order") != _STORAGE_ORDER
        or snapshot.get("identity_key_encoding") != "canonical-json-array-v1"
        or snapshot.get("time_field") is not None
        or snapshot.get("temporal_semantics") != "none"
        or snapshot.get("timezone") != "UTC"
        or snapshot.get("pit_policy") != "unsupported"
        or snapshot.get("source_available_at_field") is not None
        or snapshot.get("calendar_id") is not None
        or snapshot.get("identity_semantics") != _IDENTITY_SEMANTICS
    ):
        raise OpenDataSinaFzbSnapshotError("snapshot_contract_mismatch")
    window = snapshot.get("window")
    if (
        not isinstance(window, dict)
        or set(window) != {"start", "end", "end_exclusive"}
        or window.get("start") is not None
        or window.get("end") is not None
        or window.get("end_exclusive") is not True
    ):
        raise OpenDataSinaFzbSnapshotError("snapshot_window_invalid")
    selection = snapshot.get("selection")
    if (
        not isinstance(selection, dict)
        or set(selection) != {"instrument_id", "capture_id"}
        or selection.get("instrument_id") != instrument_id
        or selection.get("capture_id") != capture_id
    ):
        raise OpenDataSinaFzbSnapshotError("snapshot_selection_mismatch")
    if snapshot.get("page_size") != _ROW_PAGE_SIZE or type(snapshot.get("page_size")) is not int:
        raise OpenDataSinaFzbSnapshotError("snapshot_metadata_invalid")
    if (
        type(snapshot.get("record_count")) is not int
        or not 0 <= snapshot["record_count"] <= _MAX_ROWS
    ):
        raise OpenDataSinaFzbSnapshotError("snapshot_row_limit_exceeded")
    for field in ("contract_sha256", "selection_sha256", "content_sha256"):
        if type(snapshot.get(field)) is not str or _SHA256.fullmatch(snapshot[field]) is None:
            raise OpenDataSinaFzbSnapshotError("snapshot_hash_invalid")
    _validate_timestamp(snapshot.get("as_of"), nullable=False)
    created_at = _validate_timestamp(snapshot.get("created_at"), nullable=False)
    expires_at = _validate_timestamp(snapshot.get("expires_at"), nullable=False)
    if expires_at <= created_at:
        raise OpenDataSinaFzbSnapshotError("snapshot_expiry_invalid")
    return snapshot


def _validate_page(
    page: object,
    *,
    snapshot: dict[str, Any],
    instrument_id: str,
    capture_id: str,
) -> tuple[list[dict[str, Any]], str | None, bool, int]:
    expected_fields = _SNAPSHOT_FIELDS | _PAGE_FIELDS
    if not isinstance(page, dict) or set(page) != expected_fields:
        raise OpenDataSinaFzbSnapshotError("records_page_invalid")
    page_snapshot = {key: page[key] for key in _SNAPSHOT_FIELDS}
    _validate_snapshot(
        page_snapshot,
        instrument_id=instrument_id,
        publication_id=snapshot["publication_id"],
        capture_id=capture_id,
    )
    if _canonical_json_bytes(page_snapshot) != _canonical_json_bytes(snapshot):
        raise OpenDataSinaFzbSnapshotError("records_snapshot_mismatch")
    meta = page.get("meta")
    if not isinstance(meta, dict) or set(meta) != _META_FIELDS:
        raise OpenDataSinaFzbSnapshotError("records_page_meta_invalid")
    if (
        _canonical_json_bytes(meta.get("snapshot")) != _canonical_json_bytes(snapshot)
        or meta.get("ordering_fields") != list(_BUSINESS_FIELDS)
        or meta.get("storage_order") != _STORAGE_ORDER
        or meta.get("identity_key_encoding") != "canonical-json-array-v1"
    ):
        raise OpenDataSinaFzbSnapshotError("records_page_meta_mismatch")
    rows = page.get("rows")
    count = page.get("count")
    next_cursor = page.get("next_cursor")
    has_more = page.get("has_more")
    if (
        not isinstance(rows, list)
        or type(count) is not int
        or count != len(rows)
        or count > _ROW_PAGE_SIZE
        or type(has_more) is not bool
        or (next_cursor is not None and not _valid_cursor(next_cursor))
        or has_more != (next_cursor is not None)
        or (has_more and count == 0)
    ):
        raise OpenDataSinaFzbSnapshotError("records_page_count_invalid")
    validated_rows: list[dict[str, Any]] = []
    total_occurrences = 0
    for row in rows:
        total_occurrences += _validate_row(
            row,
            snapshot=snapshot,
            instrument_id=instrument_id,
            capture_id=capture_id,
        )
        validated_rows.append(row)
    return validated_rows, next_cursor, has_more, total_occurrences


def _validate_row(
    row: object,
    *,
    snapshot: dict[str, Any],
    instrument_id: str,
    capture_id: str,
) -> int:
    if not isinstance(row, dict) or set(row) != _ROW_FIELDS:
        raise OpenDataSinaFzbSnapshotError("record_shape_invalid")
    if row.get("dataset_id") != _DATASET_ID:
        raise OpenDataSinaFzbSnapshotError("record_scope_mismatch")
    business_key = row.get("business_key")
    if type(business_key) is not str or not business_key or len(business_key) > 512:
        raise OpenDataSinaFzbSnapshotError("record_business_key_invalid")
    revision = row.get("revision")
    publication_sequence = row.get("publication_sequence")
    row_publication_id = row.get("publication_id")
    if (
        type(revision) is not int
        or revision < 1
        or type(publication_sequence) is not int
        or publication_sequence < 1
        or publication_sequence > snapshot["sequence"]
        or type(row_publication_id) is not str
        or _PUBLICATION_ID.fullmatch(row_publication_id) is None
    ):
        raise OpenDataSinaFzbSnapshotError("record_publication_invalid")
    if (
        publication_sequence == snapshot["sequence"]
        and row_publication_id != snapshot["publication_id"]
    ):
        raise OpenDataSinaFzbSnapshotError("record_publication_mismatch")
    if any(
        row.get(field) is not None
        for field in ("business_date", "event_at", "source_published_at", "available_at")
    ):
        raise OpenDataSinaFzbSnapshotError("record_temporal_scope_invalid")
    observed_at = _validate_timestamp(row.get("observed_at"), nullable=False)
    if type(row.get("record_hash")) is not str or _SHA256.fullmatch(row["record_hash"]) is None:
        raise OpenDataSinaFzbSnapshotError("record_hash_invalid")
    payload = row.get("payload")
    if not isinstance(payload, dict) or set(payload) != _PAYLOAD_FIELDS:
        raise OpenDataSinaFzbSnapshotError("record_payload_shape_invalid")
    occurrences = _validate_payload(
        payload,
        instrument_id=instrument_id,
        capture_id=capture_id,
    )
    retrieved_at_utc = _validate_timestamp(payload.get("retrieved_at_utc"), nullable=False)
    if observed_at is None or retrieved_at_utc is None or observed_at != retrieved_at_utc:
        raise OpenDataSinaFzbSnapshotError("record_observation_time_mismatch")
    expected_key = json.dumps(
        [instrument_id, capture_id, "fzb", payload["report_period"]],
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )
    if business_key != expected_key:
        raise OpenDataSinaFzbSnapshotError("record_business_key_mismatch")
    return occurrences


def _validate_payload(payload: dict[str, Any], *, instrument_id: str, capture_id: str) -> int:
    if (
        payload.get("instrument_id") != instrument_id
        or payload.get("capture_id") != capture_id
        or payload.get("statement_code") != "fzb"
    ):
        raise OpenDataSinaFzbSnapshotError("record_payload_scope_mismatch")
    if (
        type(payload.get("report_period")) is not str
        or _ISO_DATE.fullmatch(payload["report_period"]) is None
        or not _valid_date(payload["report_period"])
        or type(payload.get("source_paper_code")) is not str
        or payload["source_paper_code"] != _sina_paper_code(instrument_id)
        or type(payload.get("published_on")) is not str
        or _ISO_DATE.fullmatch(payload["published_on"]) is None
        or not _valid_date(payload["published_on"])
        or payload.get("publication_precision") != "date"
        or type(payload.get("source_update_epoch_seconds")) is not int
        or payload["source_update_epoch_seconds"] <= 0
        or type(payload.get("source_updated_at_timezone")) is not str
        or payload["source_updated_at_timezone"] != "Asia/Shanghai"
        or type(payload.get("currency")) is not str
        or not payload["currency"]
    ):
        raise OpenDataSinaFzbSnapshotError("record_payload_invalid")
    source_updated_at = _validate_timestamp(payload.get("source_updated_at"), nullable=False)
    retrieved_at_utc = _validate_timestamp(payload.get("retrieved_at_utc"), nullable=False)
    if (
        source_updated_at is None
        or source_updated_at.utcoffset() != timedelta(hours=8)
        or retrieved_at_utc is None
        or retrieved_at_utc.utcoffset() != timedelta(0)
        or not payload["retrieved_at_utc"].endswith("Z")
    ):
        raise OpenDataSinaFzbSnapshotError("record_payload_invalid")
    try:
        source_update_epoch = datetime.fromtimestamp(
            payload["source_update_epoch_seconds"], tz=timezone.utc
        )
    except (OverflowError, OSError, ValueError):
        raise OpenDataSinaFzbSnapshotError("record_payload_invalid") from None
    if source_update_epoch.astimezone(source_updated_at.tzinfo) != source_updated_at:
        raise OpenDataSinaFzbSnapshotError("record_payload_invalid")
    for field in ("period_metadata", "report_metadata"):
        _validate_scalar_object(payload.get(field))
    entries = payload.get("entries")
    if not isinstance(entries, list) or len(entries) > _MAX_REPORT_ENTRIES:
        raise OpenDataSinaFzbSnapshotError("record_entries_invalid")
    seen_ordinals: list[int] = []
    previous_first_ordinal = -1
    for entry in entries:
        if not isinstance(entry, dict):
            raise OpenDataSinaFzbSnapshotError("record_entry_invalid")
        kind = entry.get("kind")
        if kind == "item":
            expected = {
                "kind",
                "source_item_id",
                "source_title",
                "source_ordinals",
                "raw_value",
                "value_state",
                "source_metadata",
            }
            if set(entry) != expected:
                raise OpenDataSinaFzbSnapshotError("record_entry_invalid")
            if (
                type(entry.get("source_item_id")) is not str
                or not entry["source_item_id"]
                or type(entry.get("source_title")) is not str
                or not entry["source_title"]
                or (entry.get("raw_value") is not None and type(entry["raw_value"]) is not str)
            ):
                raise OpenDataSinaFzbSnapshotError("record_entry_invalid")
            expected_state = (
                "null"
                if entry["raw_value"] is None
                else "empty"
                if entry["raw_value"] == ""
                else "present"
            )
            if entry.get("value_state") != expected_state:
                raise OpenDataSinaFzbSnapshotError("record_entry_invalid")
        elif kind == "group_marker":
            expected = {
                "kind",
                "source_ordinals",
                "source_group_no",
                "source_title",
                "raw_item_field",
                "raw_item_value",
                "source_metadata",
            }
            if set(entry) != expected:
                raise OpenDataSinaFzbSnapshotError("record_entry_invalid")
            if (
                type(entry.get("source_group_no")) is not int
                or entry["source_group_no"] not in {1, 2, 3, 4, 5}
                or type(entry.get("source_title")) is not str
                or not entry["source_title"]
                or entry.get("raw_item_field") != ""
                or entry.get("raw_item_value") != ""
            ):
                raise OpenDataSinaFzbSnapshotError("record_entry_invalid")
        else:
            raise OpenDataSinaFzbSnapshotError("record_entry_invalid")
        _validate_scalar_object(entry.get("source_metadata"))
        ordinals = entry.get("source_ordinals")
        if (
            not isinstance(ordinals, list)
            or not ordinals
            or len(ordinals) > _MAX_REPORT_ENTRIES
            or any(type(value) is not int or value < 0 for value in ordinals)
            or any(left >= right for left, right in zip(ordinals, ordinals[1:], strict=False))
            or ordinals[0] <= previous_first_ordinal
        ):
            raise OpenDataSinaFzbSnapshotError("record_ordinals_invalid")
        previous_first_ordinal = ordinals[0]
        seen_ordinals.extend(ordinals)
    if len(seen_ordinals) > _MAX_REPORT_ENTRIES or sorted(seen_ordinals) != list(
        range(len(seen_ordinals))
    ):
        raise OpenDataSinaFzbSnapshotError("record_ordinals_invalid")
    return len(seen_ordinals)


def _validate_scalar_object(value: object) -> None:
    if not isinstance(value, dict):
        raise OpenDataSinaFzbSnapshotError("record_metadata_invalid")
    for key, item in value.items():
        if (
            type(key) is not str
            or not key
            or not (item is None or type(item) in {str, bool, int, float})
        ):
            raise OpenDataSinaFzbSnapshotError("record_metadata_invalid")
        if type(item) is float and not math.isfinite(item):
            raise OpenDataSinaFzbSnapshotError("record_metadata_invalid")


def _validate_timestamp(value: object, *, nullable: bool) -> datetime | None:
    if nullable and value is None:
        return None
    if type(value) is not str or not value or len(value) > 40:
        raise OpenDataSinaFzbSnapshotError("timestamp_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise OpenDataSinaFzbSnapshotError("timestamp_invalid") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise OpenDataSinaFzbSnapshotError("timestamp_invalid")
    return parsed


def _valid_date(value: str) -> bool:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date().isoformat() == value
    except ValueError:
        return False


def _validate_json_tree(value: Any) -> None:
    pending: list[tuple[Any, int]] = [(value, 0)]
    nodes = 0
    while pending:
        current, depth = pending.pop()
        nodes += 1
        if nodes > _MAX_JSON_NODES or depth > _MAX_JSON_DEPTH:
            raise ValueError("response JSON exceeds structural limits")
        if type(current) is float and not math.isfinite(current):
            raise ValueError("response JSON contains a non-finite number")
        if isinstance(current, dict):
            pending.extend((child, depth + 1) for child in current.values())
        elif isinstance(current, list):
            pending.extend((child, depth + 1) for child in current)


def _json_contains_secret(value: Any, secret: str) -> bool:
    if not secret:
        return False
    pending = [value]
    while pending:
        current = pending.pop()
        if isinstance(current, str):
            if secret in current:
                return True
        elif isinstance(current, dict):
            for key, child in current.items():
                if secret in key:
                    return True
                pending.append(child)
        elif isinstance(current, list):
            pending.extend(current)
    return False


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _safe_configuration_error(value: str | None) -> str | None:
    if value is None:
        return None
    return value if value in _SAFE_CONFIGURATION_ERRORS else "configuration_invalid"


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def _canonical_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError):
        raise OpenDataSinaFzbSnapshotError("response_json_invalid") from None


def _valid_cursor(value: object) -> bool:
    return (
        type(value) is str
        and bool(value)
        and len(value) <= _MAX_CURSOR_LENGTH
        and not any(ord(character) < 32 for character in value)
    )


def _sina_paper_code(instrument_id: str) -> str:
    code, _separator, exchange = instrument_id.partition(".")
    return f"{exchange.lower()}{code}"


def _http_error(status_code: int) -> OpenDataSinaFzbSnapshotError:
    code = {
        401: "http_401_unauthorized",
        403: "http_403_forbidden",
        404: "http_404_not_found",
        410: "http_410_snapshot_expired",
        413: "http_413_too_large",
        422: "http_422_invalid_request",
        429: "http_429_rate_limited",
    }.get(status_code, "http_server_error" if status_code >= 500 else "http_error")
    return OpenDataSinaFzbSnapshotError(code, status_code=status_code)


def _parse_allowed_origins(
    host_entries: Iterable[str],
) -> tuple[frozenset[tuple[str, int]], str | None]:
    origins: set[tuple[str, int]] = set()
    for raw_entry in host_entries:
        entry = raw_entry.strip()
        if not entry:
            continue
        try:
            parsed = urlsplit(f"//{entry}")
            hostname = parsed.hostname
            configured_port = parsed.port
        except ValueError:
            return frozenset(), "allowed_hosts_invalid"
        if (
            not hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
            or entry.endswith(":")
            or any(character.isspace() for character in entry)
            or "\\" in entry
            or configured_port == 0
        ):
            return frozenset(), "allowed_hosts_invalid"
        origins.add((hostname.lower().rstrip("."), configured_port or 443))
    return frozenset(origins), None


def _is_loopback_host(hostname: str) -> bool:
    if hostname.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


__all__ = [
    "OpenDataSinaFzbSnapshotError",
    "OpenDataSinaFzbSnapshotReader",
    "SinaFzbSnapshotResult",
]
