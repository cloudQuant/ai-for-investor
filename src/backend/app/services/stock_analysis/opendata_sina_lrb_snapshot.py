"""Read one explicitly selected, source-native Sina LRB capture from OpenData.

The reader verifies the complete pinned publication snapshot and preserves its
source-native row envelopes for audit. It does not decode node tables, infer
accounting semantics, normalize values, discover captures, or claim historical
completeness.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
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

_DATASET_ID = "sina_lrb_report_observations"
_SOURCE = {"source": "sina", "source_id": "sina-lrb"}
_SCHEMA_VERSION = "source-native-report-v1"
_SEMANTIC_VERSION = "sina-lrb-source-native-v1"
_RESPONSE_ENCODING = "sina-lrb-node-table-v1"
_CONTRACT_SHA256 = "a8aec8a825b481a4dbf17845df36ef6c15a8caa52929120c563270683eecf459"
_SCHEMA_FIELDS = (
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
_PAYLOAD_FIELDS = frozenset(name for name, _data_type, _nullable in _SCHEMA_FIELDS)
_BUSINESS_FIELDS = (
    "instrument_id",
    "capture_id",
    "statement_code",
    "record_kind",
    "record_key",
)
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
_CURSOR_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_REPORT_KEY_MAX = 4_096
_ROW_PAGE_SIZE = 30
_MAX_REPORTS = 256
_MAX_ROWS = _MAX_REPORTS + 1  # One context row plus each report-list row.
_MAX_PAGES = 9
_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
_MAX_TOTAL_RESPONSE_BYTES = 64 * 1024 * 1024
_MAX_RECORD_BYTES = 192 * 1024
_MAX_CURSOR_LENGTH = 8_192
_STREAM_CHUNK_BYTES = 64 * 1024
_MAX_JSON_DEPTH = 32
_MAX_JSON_NODES = 1_000_000
_MAX_NODE_TABLE_NODES = 200_000
_MAX_VALUE_TEXT = 4_096
_MAX_DECIMAL_EXPONENT = 1_000_000
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


class OpenDataSinaLrbSnapshotError(RuntimeError):
    """Stable failure code that never includes credentials, URLs, or response bodies."""

    def __init__(self, code: str, *, status_code: int | None = None) -> None:
        self.code = code
        self.status_code = status_code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class SinaLrbSnapshotResult:
    """One complete pinned LRB capture, still in OpenData's raw row envelope.

    Per-row record hashes are recomputed from the exact publication canonical
    form. The snapshot selection/content hashes are only shape-checked because
    OpenData includes a private access-scope binding in their preimages and
    does not expose that binding through the API.
    """

    snapshot: dict[str, Any]
    records: tuple[dict[str, Any], ...]
    page_count: int
    response_bytes: int
    report_count: int
    record_hash_verification: str = "verified"
    selection_hash_verification: str = "unavailable_access_scope_not_returned"
    content_hash_verification: str = "unavailable_access_scope_not_returned"
    completeness: str = "unknown"
    historical_as_of_status: str = "unavailable"
    eligible_for_decision_or_backtest: bool = False


class OpenDataSinaLrbSnapshotReader:
    """Fetch and verify one exact publication/instrument/capture selection."""

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
    ) -> OpenDataSinaLrbSnapshotReader:
        """Resolve the shared OpenData credential reference without exposing it."""
        import os

        if allowed_hosts is None:
            allowed_hosts = os.environ.get("STOCK_ANALYSIS_OPENDATA_SINA_LRB_ALLOWED_HOSTS", "")
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
    ) -> SinaLrbSnapshotResult:
        """Read exactly one explicitly named LRB capture without partial results."""
        _validate_request_identity(
            instrument_id=instrument_id,
            publication_id=publication_id,
            capture_id=capture_id,
        )
        endpoint = self._endpoint_url()
        if self._configuration_error is not None:
            raise OpenDataSinaLrbSnapshotError(self._configuration_error)
        if self._credentials is None:
            raise OpenDataSinaLrbSnapshotError("credential_missing")

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
            record_count = snapshot["record_count"]
            if record_count > _MAX_ROWS:
                raise OpenDataSinaLrbSnapshotError("snapshot_row_limit_exceeded")

            records: list[dict[str, Any]] = []
            seen_business_keys: set[str] = set()
            seen_cursors: set[str] = set()
            previous_business_key: str | None = None
            report_list_ordinals: set[int] = set()
            report_date_ordinals: set[int] = set()
            shared_identity: tuple[str, str, str] | None = None
            context_count = 0
            cursor: str | None = None
            page_count = 0
            while True:
                self._check_deadline(started_at)
                if page_count >= _MAX_PAGES:
                    raise OpenDataSinaLrbSnapshotError("snapshot_page_limit_exceeded")
                params = {"snapshot_id": snapshot["snapshot_id"]}
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
                page_count += 1
                page_records, next_cursor, has_more = _validate_page(
                    page,
                    snapshot=snapshot,
                    instrument_id=instrument_id,
                    capture_id=capture_id,
                )
                for record in page_records:
                    business_key = record["business_key"]
                    if business_key in seen_business_keys:
                        raise OpenDataSinaLrbSnapshotError("duplicate_business_key")
                    if previous_business_key is not None and business_key <= previous_business_key:
                        raise OpenDataSinaLrbSnapshotError("record_order_invalid")
                    if len(_canonical_json_bytes(record)) > _MAX_RECORD_BYTES:
                        raise OpenDataSinaLrbSnapshotError("record_too_large")
                    identity = _validate_record(
                        record,
                        snapshot=snapshot,
                        instrument_id=instrument_id,
                        capture_id=capture_id,
                    )
                    if shared_identity is None:
                        shared_identity = identity
                    elif identity != shared_identity:
                        raise OpenDataSinaLrbSnapshotError("record_identity_mismatch")
                    payload = record["payload"]
                    if payload["record_kind"] == "context":
                        context_count += 1
                    else:
                        report_list_ordinals.add(payload["report_list_ordinal"])
                        report_date_ordinals.add(payload["report_date_ordinal"])
                    seen_business_keys.add(business_key)
                    previous_business_key = business_key
                    records.append(record)
                    if len(records) > _MAX_ROWS:
                        raise OpenDataSinaLrbSnapshotError("snapshot_row_limit_exceeded")
                if not has_more:
                    break
                assert next_cursor is not None
                if next_cursor in seen_cursors or next_cursor == cursor:
                    raise OpenDataSinaLrbSnapshotError("snapshot_cursor_repeated")
                seen_cursors.add(next_cursor)
                cursor = next_cursor

        self._check_deadline(started_at)
        if len(records) != record_count or page_count < 1:
            raise OpenDataSinaLrbSnapshotError("snapshot_incomplete")
        report_count = sum(record["payload"]["record_kind"] == "report" for record in records)
        if records:
            if context_count != 1:
                raise OpenDataSinaLrbSnapshotError("record_payload_invalid")
            if report_list_ordinals != set(range(report_count)):
                raise OpenDataSinaLrbSnapshotError("record_payload_invalid")
            if report_date_ordinals != set(range(report_count)):
                raise OpenDataSinaLrbSnapshotError("record_payload_invalid")
        return SinaLrbSnapshotResult(
            snapshot=snapshot,
            records=tuple(records),
            page_count=page_count,
            response_bytes=total_bytes,
            report_count=report_count,
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
            raise OpenDataSinaLrbSnapshotError(self._configuration_error)
        if self._credentials is None:
            raise OpenDataSinaLrbSnapshotError("credential_missing")
        if max_response_bytes <= 0:
            raise OpenDataSinaLrbSnapshotError("total_response_too_large")
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
                    raise OpenDataSinaLrbSnapshotError("content_type_invalid")
                async for chunk in response.aiter_bytes(chunk_size=_STREAM_CHUNK_BYTES):
                    if len(response_bytes) + len(chunk) > response_limit:
                        raise OpenDataSinaLrbSnapshotError("response_too_large")
                    response_bytes.extend(chunk)
            return response_bytes

        try:
            response_bytes = await asyncio.wait_for(read_body(), timeout=remaining)
        except OpenDataSinaLrbSnapshotError:
            raise
        except (TimeoutError, asyncio.TimeoutError, httpx.TimeoutException):
            raise OpenDataSinaLrbSnapshotError("deadline_exceeded") from None
        except httpx.TransportError:
            raise OpenDataSinaLrbSnapshotError("transport_error") from None
        except Exception:
            raise OpenDataSinaLrbSnapshotError("response_read_failed") from None

        if self._credentials.api_key.encode("utf-8") in response_bytes:
            raise OpenDataSinaLrbSnapshotError("credential_reflected_in_response")
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
            raise OpenDataSinaLrbSnapshotError("response_json_invalid") from None
        if _json_contains_secret(payload, self._credentials.api_key):
            raise OpenDataSinaLrbSnapshotError("credential_reflected_in_response")
        return payload, len(response_bytes)

    def _endpoint_url(self) -> str:
        if self._configuration_error is not None:
            raise OpenDataSinaLrbSnapshotError(self._configuration_error)
        if self._credentials is None:
            raise OpenDataSinaLrbSnapshotError("credential_missing")
        try:
            parsed = urlsplit(self._credentials.base_url)
            hostname = parsed.hostname
            configured_port = parsed.port
        except ValueError:
            raise OpenDataSinaLrbSnapshotError("base_url_invalid") from None
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
            raise OpenDataSinaLrbSnapshotError("base_url_invalid")
        normalized_hostname = hostname.lower().rstrip(".")
        port = configured_port or (443 if parsed.scheme == "https" else 80)
        is_loopback = _is_loopback_host(normalized_hostname)
        if parsed.scheme == "http" and not is_loopback:
            raise OpenDataSinaLrbSnapshotError("base_url_insecure_transport")
        if not is_loopback and (normalized_hostname, port) not in self._allowed_origins:
            raise OpenDataSinaLrbSnapshotError("base_url_host_not_allowed")
        return self._credentials.base_url.rstrip("/")

    @staticmethod
    def _remaining_seconds(started_at: float) -> float:
        remaining = _TOTAL_TIMEOUT_SECONDS - (asyncio.get_running_loop().time() - started_at)
        if remaining <= 0:
            raise OpenDataSinaLrbSnapshotError("deadline_exceeded")
        return remaining

    @classmethod
    def _check_deadline(cls, started_at: float) -> None:
        cls._remaining_seconds(started_at)


def _validate_request_identity(
    *, instrument_id: object, publication_id: object, capture_id: object
) -> None:
    if type(instrument_id) is not str or _INSTRUMENT_ID.fullmatch(instrument_id) is None:
        raise OpenDataSinaLrbSnapshotError("instrument_id_invalid")
    if type(publication_id) is not str or _PUBLICATION_ID.fullmatch(publication_id) is None:
        raise OpenDataSinaLrbSnapshotError("publication_id_invalid")
    if type(capture_id) is not str or _CAPTURE_ID.fullmatch(capture_id) is None:
        raise OpenDataSinaLrbSnapshotError("capture_id_invalid")


def _validate_snapshot(
    snapshot: object,
    *,
    instrument_id: str,
    publication_id: str,
    capture_id: str,
) -> dict[str, Any]:
    if not isinstance(snapshot, dict) or set(snapshot) != _SNAPSHOT_FIELDS:
        raise OpenDataSinaLrbSnapshotError("snapshot_metadata_invalid")
    if (
        type(snapshot.get("snapshot_id")) is not str
        or _OPAQUE_ID.fullmatch(snapshot["snapshot_id"]) is None
        or snapshot.get("dataset_id") != _DATASET_ID
        or snapshot.get("publication_id") != publication_id
        or _PUBLICATION_ID.fullmatch(snapshot.get("publication_id", "")) is None
    ):
        raise OpenDataSinaLrbSnapshotError("snapshot_scope_mismatch")
    if type(snapshot.get("sequence")) is not int or snapshot["sequence"] < 1:
        raise OpenDataSinaLrbSnapshotError("snapshot_metadata_invalid")
    if (
        snapshot.get("schema_version") != _SCHEMA_VERSION
        or snapshot.get("semantic_version") != _SEMANTIC_VERSION
        or snapshot.get("source") != _SOURCE
        or snapshot.get("schema")
        != [
            {"name": name, "data_type": data_type, "nullable": nullable}
            for name, data_type, nullable in _SCHEMA_FIELDS
        ]
    ):
        raise OpenDataSinaLrbSnapshotError("snapshot_contract_mismatch")
    if (
        snapshot.get("quality") != {"status": "unknown", "report_id": None, "issue_count": 0}
        or snapshot.get("field_units")
        != {"report_list_ordinal": "source_ordinal", "report_date_ordinal": "source_ordinal"}
        or snapshot.get("field_currencies") != {}
        or snapshot.get("field_adjustments") != {}
        or snapshot.get("currency") is not None
        or snapshot.get("adjustment_basis") != "not_applicable"
        or snapshot.get("asset_class") != "equity"
        or snapshot.get("frequency") != "irregular"
        or snapshot.get("record_kind") != "table"
    ):
        raise OpenDataSinaLrbSnapshotError("snapshot_contract_mismatch")
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
        raise OpenDataSinaLrbSnapshotError("snapshot_contract_mismatch")
    if (
        type(snapshot.get("contract_sha256")) is not str
        or snapshot["contract_sha256"] != _CONTRACT_SHA256
        or _SHA256.fullmatch(snapshot["contract_sha256"]) is None
    ):
        raise OpenDataSinaLrbSnapshotError("snapshot_contract_hash_mismatch")
    window = snapshot.get("window")
    if (
        not isinstance(window, dict)
        or set(window) != {"start", "end", "end_exclusive"}
        or window.get("start") is not None
        or window.get("end") is not None
        or window.get("end_exclusive") is not True
    ):
        raise OpenDataSinaLrbSnapshotError("snapshot_window_invalid")
    selection = snapshot.get("selection")
    if (
        not isinstance(selection, dict)
        or set(selection) != {"instrument_id", "capture_id"}
        or selection.get("instrument_id") != instrument_id
        or selection.get("capture_id") != capture_id
    ):
        raise OpenDataSinaLrbSnapshotError("snapshot_selection_mismatch")
    if type(snapshot.get("page_size")) is not int or snapshot["page_size"] != _ROW_PAGE_SIZE:
        raise OpenDataSinaLrbSnapshotError("snapshot_metadata_invalid")
    if (
        type(snapshot.get("record_count")) is not int
        or not 0 <= snapshot["record_count"] <= _MAX_ROWS
    ):
        raise OpenDataSinaLrbSnapshotError("snapshot_row_limit_exceeded")
    for field in ("selection_sha256", "content_sha256"):
        if type(snapshot.get(field)) is not str or _SHA256.fullmatch(snapshot[field]) is None:
            raise OpenDataSinaLrbSnapshotError("snapshot_hash_invalid")
    _validate_timestamp(snapshot.get("as_of"), nullable=False)
    created_at = _validate_timestamp(snapshot.get("created_at"), nullable=False)
    expires_at = _validate_timestamp(snapshot.get("expires_at"), nullable=False)
    if created_at is None or expires_at is None or expires_at <= created_at:
        raise OpenDataSinaLrbSnapshotError("snapshot_expiry_invalid")
    return snapshot


def _validate_page(
    page: object,
    *,
    snapshot: dict[str, Any],
    instrument_id: str,
    capture_id: str,
) -> tuple[list[dict[str, Any]], str | None, bool]:
    expected_fields = _SNAPSHOT_FIELDS | _PAGE_FIELDS
    if not isinstance(page, dict) or set(page) != expected_fields:
        raise OpenDataSinaLrbSnapshotError("records_page_invalid")
    page_snapshot = {key: page[key] for key in _SNAPSHOT_FIELDS}
    _validate_snapshot(
        page_snapshot,
        instrument_id=instrument_id,
        publication_id=snapshot["publication_id"],
        capture_id=capture_id,
    )
    if _canonical_json_bytes(page_snapshot) != _canonical_json_bytes(snapshot):
        raise OpenDataSinaLrbSnapshotError("records_page_mismatch")
    meta = page.get("meta")
    if not isinstance(meta, dict) or set(meta) != _META_FIELDS:
        raise OpenDataSinaLrbSnapshotError("records_page_meta_invalid")
    if (
        _canonical_json_bytes(meta.get("snapshot")) != _canonical_json_bytes(snapshot)
        or meta.get("ordering_fields") != list(_BUSINESS_FIELDS)
        or meta.get("storage_order") != _STORAGE_ORDER
        or meta.get("identity_key_encoding") != "canonical-json-array-v1"
    ):
        raise OpenDataSinaLrbSnapshotError("records_page_mismatch")
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
        raise OpenDataSinaLrbSnapshotError("records_page_count_invalid")
    if len(rows) == 0 and snapshot["record_count"] != 0:
        raise OpenDataSinaLrbSnapshotError("records_page_count_invalid")
    return rows, next_cursor, has_more


def _validate_record(
    record: object,
    *,
    snapshot: dict[str, Any],
    instrument_id: str,
    capture_id: str,
) -> tuple[str, str, str]:
    if not isinstance(record, dict) or set(record) != _ROW_FIELDS:
        raise OpenDataSinaLrbSnapshotError("record_shape_invalid")
    if record.get("dataset_id") != _DATASET_ID:
        raise OpenDataSinaLrbSnapshotError("record_scope_mismatch")
    business_key = record.get("business_key")
    if type(business_key) is not str or not business_key or len(business_key) > 8_192:
        raise OpenDataSinaLrbSnapshotError("record_identity_mismatch")
    revision = record.get("revision")
    publication_sequence = record.get("publication_sequence")
    row_publication_id = record.get("publication_id")
    if (
        type(revision) is not int
        or revision < 1
        or type(publication_sequence) is not int
        or publication_sequence < 1
        or publication_sequence > snapshot["sequence"]
        or type(row_publication_id) is not str
        or _PUBLICATION_ID.fullmatch(row_publication_id) is None
    ):
        raise OpenDataSinaLrbSnapshotError("record_publication_invalid")
    if (
        publication_sequence == snapshot["sequence"]
        and row_publication_id != snapshot["publication_id"]
    ):
        raise OpenDataSinaLrbSnapshotError("record_publication_mismatch")
    if any(
        record.get(field) is not None
        for field in ("business_date", "event_at", "source_published_at", "available_at")
    ):
        raise OpenDataSinaLrbSnapshotError("record_temporal_scope_invalid")
    observed_at = _validate_timestamp(record.get("observed_at"), nullable=False)
    if (
        type(record.get("record_hash")) is not str
        or _SHA256.fullmatch(record["record_hash"]) is None
    ):
        raise OpenDataSinaLrbSnapshotError("record_hash_invalid")
    payload = record.get("payload")
    if not isinstance(payload, dict) or set(payload) != _PAYLOAD_FIELDS:
        raise OpenDataSinaLrbSnapshotError("record_payload_invalid")
    common_identity = _validate_payload(
        payload,
        instrument_id=instrument_id,
        capture_id=capture_id,
    )
    retrieved_at = _validate_timestamp(payload.get("retrieved_at_utc"), nullable=False)
    if observed_at is None or retrieved_at is None or observed_at != retrieved_at:
        raise OpenDataSinaLrbSnapshotError("record_temporal_scope_invalid")
    expected_key = json.dumps(
        [instrument_id, capture_id, "lrb", payload["record_kind"], payload["record_key"]],
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )
    if business_key != expected_key:
        raise OpenDataSinaLrbSnapshotError("record_identity_mismatch")
    canonical_record = {
        "business_key": business_key,
        "business_date": record["business_date"],
        "event_at": _canonical_publication_timestamp(record["event_at"]),
        "observed_at": _canonical_publication_timestamp(record["observed_at"]),
        "source_published_at": _canonical_publication_timestamp(record["source_published_at"]),
        "available_at": _canonical_publication_timestamp(record["available_at"]),
        "payload": payload,
        "selection": {"instrument_id": instrument_id, "capture_id": capture_id},
    }
    expected_record_hash = hashlib.sha256(_canonical_json_bytes(canonical_record)).hexdigest()
    if not hmac.compare_digest(record["record_hash"], expected_record_hash):
        raise OpenDataSinaLrbSnapshotError("record_hash_mismatch")
    return common_identity


def _validate_payload(
    payload: dict[str, Any], *, instrument_id: str, capture_id: str
) -> tuple[str, str, str]:
    paper_code = _sina_paper_code(instrument_id)
    if (
        payload.get("instrument_id") != instrument_id
        or payload.get("capture_id") != capture_id
        or payload.get("statement_code") != "lrb"
        or payload.get("source_paper_code") != paper_code
        or payload.get("response_encoding") != _RESPONSE_ENCODING
        or type(payload.get("record_key")) is not str
        or not payload["record_key"]
        or len(payload["record_key"]) > _REPORT_KEY_MAX
        or type(payload.get("response_sha256")) is not str
        or _SHA256.fullmatch(payload["response_sha256"]) is None
    ):
        raise OpenDataSinaLrbSnapshotError("record_payload_invalid")
    retrieved_at_text = payload.get("retrieved_at_utc")
    retrieved_at = _validate_timestamp(retrieved_at_text, nullable=False)
    if (
        retrieved_at is None
        or not isinstance(retrieved_at_text, str)
        or not retrieved_at_text.endswith("Z")
        or retrieved_at.utcoffset() != timedelta(0)
    ):
        raise OpenDataSinaLrbSnapshotError("record_payload_invalid")
    record_kind = payload["record_kind"]
    if record_kind == "context":
        if (
            payload["record_key"] != "context"
            or payload.get("report_list_key") is not None
            or payload.get("report_list_ordinal") is not None
            or payload.get("report_date_ordinal") is not None
            or payload.get("report_date_entry") is not None
            or payload.get("report_list_entry") is not None
        ):
            raise OpenDataSinaLrbSnapshotError("record_payload_invalid")
        _validate_node_table(payload.get("response_context"), context=True)
    elif record_kind == "report":
        list_key = payload.get("report_list_key")
        list_ordinal = payload.get("report_list_ordinal")
        date_ordinal = payload.get("report_date_ordinal")
        if (
            type(list_key) is not str
            or not list_key
            or len(list_key) > _REPORT_KEY_MAX
            or list_key != payload["record_key"]
            or type(list_ordinal) is not int
            or list_ordinal < 0
            or type(date_ordinal) is not int
            or date_ordinal < 0
            or payload.get("response_context") is not None
        ):
            raise OpenDataSinaLrbSnapshotError("record_payload_invalid")
        _validate_node_table(payload.get("report_date_entry"), context=False)
        _validate_node_table(payload.get("report_list_entry"), context=False)
    else:
        raise OpenDataSinaLrbSnapshotError("record_payload_invalid")
    return (
        payload["source_paper_code"],
        payload["response_sha256"],
        retrieved_at_text,
    )


def _validate_node_table(value: object, *, context: bool) -> None:
    """Check the frozen node-table wire envelope without decoding its values."""
    if not isinstance(value, dict) or set(value) != {"encoding", "root_id", "nodes"}:
        raise OpenDataSinaLrbSnapshotError("record_payload_invalid")
    nodes = value.get("nodes")
    root_id = value.get("root_id")
    if (
        value.get("encoding") != _RESPONSE_ENCODING
        or type(nodes) is not list
        or not nodes
        or len(nodes) > _MAX_NODE_TABLE_NODES
        or type(root_id) is not int
        or not 0 <= root_id < len(nodes)
    ):
        raise OpenDataSinaLrbSnapshotError("record_payload_invalid")
    if not isinstance(nodes[root_id], dict) or nodes[root_id].get("kind") != "object":
        raise OpenDataSinaLrbSnapshotError("record_payload_invalid")
    edges: list[list[int]] = [[] for _node in nodes]
    reference_names: set[str] = set()
    for expected_id, node in enumerate(nodes):
        if (
            not isinstance(node, dict)
            or node.get("id") != expected_id
            or type(node.get("id")) is not int
        ):
            raise OpenDataSinaLrbSnapshotError("record_payload_invalid")
        kind = node.get("kind")
        if kind == "null" and set(node) == {"id", "kind"}:
            continue
        if kind in {"boolean", "integer", "string"} and set(node) == {"id", "kind", "value"}:
            scalar = node["value"]
            valid = (
                (kind == "boolean" and type(scalar) is bool)
                or (
                    kind == "integer"
                    and type(scalar) is int
                    and len(str(scalar)) <= _MAX_VALUE_TEXT
                )
                or (kind == "string" and type(scalar) is str and len(scalar) <= _MAX_VALUE_TEXT)
            )
            if not valid:
                raise OpenDataSinaLrbSnapshotError("record_payload_invalid")
            continue
        if kind == "decimal" and set(node) == {"id", "kind", "sign", "digits", "exponent"}:
            sign = node["sign"]
            digits = node["digits"]
            exponent = node["exponent"]
            if (
                type(sign) is not int
                or sign not in {0, 1}
                or type(digits) is not str
                or not digits
                or len(digits) > _MAX_VALUE_TEXT
                or any(character not in "0123456789" for character in digits)
                or type(exponent) is not int
                or abs(exponent) > _MAX_DECIMAL_EXPONENT
            ):
                raise OpenDataSinaLrbSnapshotError("record_payload_invalid")
            continue
        if kind == "array" and set(node) == {"id", "kind", "items"}:
            items = node["items"]
            if type(items) is not list or len(items) > len(nodes):
                raise OpenDataSinaLrbSnapshotError("record_payload_invalid")
            edges[expected_id] = _node_references(items, len(nodes))
            continue
        if kind == "object" and set(node) == {"id", "kind", "fields"}:
            fields = node["fields"]
            if type(fields) is not list or len(fields) > len(nodes):
                raise OpenDataSinaLrbSnapshotError("record_payload_invalid")
            names: set[str] = set()
            refs: list[int] = []
            for pair in fields:
                if (
                    type(pair) is not list
                    or len(pair) != 2
                    or type(pair[0]) is not str
                    or len(pair[0]) > _MAX_VALUE_TEXT
                    or pair[0] in names
                ):
                    raise OpenDataSinaLrbSnapshotError("record_payload_invalid")
                names.add(pair[0])
                refs.extend(_node_references([pair[1]], len(nodes)))
            edges[expected_id] = refs
            continue
        if kind == "reference" and context and set(node) == {"id", "kind", "name"}:
            name = node["name"]
            if name not in {"report_date", "report_list"} or name in reference_names:
                raise OpenDataSinaLrbSnapshotError("record_payload_invalid")
            reference_names.add(name)
            continue
        raise OpenDataSinaLrbSnapshotError("record_payload_invalid")

    if context and reference_names != {"report_date", "report_list"}:
        raise OpenDataSinaLrbSnapshotError("record_payload_invalid")
    visited: set[int] = set()
    active: set[int] = set()
    pending: list[tuple[int, bool, int]] = [(root_id, False, 0)]
    while pending:
        node_id, exiting, depth = pending.pop()
        if depth > 32:
            raise OpenDataSinaLrbSnapshotError("record_payload_invalid")
        if exiting:
            active.discard(node_id)
            visited.add(node_id)
            continue
        if node_id in active:
            raise OpenDataSinaLrbSnapshotError("record_payload_invalid")
        if node_id in visited:
            raise OpenDataSinaLrbSnapshotError("record_payload_invalid")
        active.add(node_id)
        pending.append((node_id, True, depth))
        pending.extend((child_id, False, depth + 1) for child_id in reversed(edges[node_id]))
    if len(visited) != len(nodes):
        raise OpenDataSinaLrbSnapshotError("record_payload_invalid")


def _node_references(values: list[object], node_count: int) -> list[int]:
    references: list[int] = []
    for value in values:
        if type(value) is not int or not 0 <= value < node_count:
            raise OpenDataSinaLrbSnapshotError("record_payload_invalid")
        references.append(value)
    return references


def _validate_timestamp(value: object, *, nullable: bool) -> datetime | None:
    if nullable and value is None:
        return None
    if type(value) is not str or not value or len(value) > 40:
        raise OpenDataSinaLrbSnapshotError("timestamp_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise OpenDataSinaLrbSnapshotError("timestamp_invalid") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise OpenDataSinaLrbSnapshotError("timestamp_invalid")
    return parsed


def _canonical_publication_timestamp(value: object) -> str | None:
    """Reproduce publication_store's UTC/microsecond timestamp hash encoding."""
    parsed = _validate_timestamp(value, nullable=True)
    if parsed is None:
        return None
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


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
        raise OpenDataSinaLrbSnapshotError("response_json_invalid") from None


def _valid_cursor(value: object) -> bool:
    return (
        type(value) is str
        and bool(value)
        and len(value) <= _MAX_CURSOR_LENGTH
        and _CURSOR_CONTROL.search(value) is None
    )


def _sina_paper_code(instrument_id: str) -> str:
    code, _separator, exchange = instrument_id.partition(".")
    return f"{exchange.lower()}{code}"


def _http_error(status_code: int) -> OpenDataSinaLrbSnapshotError:
    code = {
        401: "http_401_unauthorized",
        403: "http_403_forbidden",
        404: "http_404_not_found",
        410: "http_410_snapshot_expired",
        413: "http_413_too_large",
        422: "http_422_invalid_request",
        429: "http_429_rate_limited",
    }.get(status_code, "http_server_error" if status_code >= 500 else "http_error")
    return OpenDataSinaLrbSnapshotError(code, status_code=status_code)


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
    "OpenDataSinaLrbSnapshotError",
    "OpenDataSinaLrbSnapshotReader",
    "SinaLrbSnapshotResult",
]
