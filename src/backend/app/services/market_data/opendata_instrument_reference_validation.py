"""Validation helpers decomposed from opendata_instrument_reference."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping
from datetime import date, datetime
from typing import Any

from pydantic import JsonValue

_PROFILE_VERSION = "od.instrument-reference.v1"
_SCHEMA_VERSION = "1"
_SEMANTIC_VERSION = "1.0.0"
_SHA256 = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_SYMBOL = re.compile(r"^[0-9]{6}$", re.ASCII)
_PROTOCOL_INVALID = "OPENDATA_REFERENCE_PROTOCOL_INVALID"
_LIMIT_EXCEEDED = "OPENDATA_REFERENCE_LIMIT_EXCEEDED"
_ALIAS_KEYS = frozenset({"alias", "alias_version", "evidence_ref", "valid_from", "valid_through"})


def validate_page_contract_metadata(
    page: dict[str, JsonValue],
    snapshot: dict[str, JsonValue],
    snapshot_meta: dict[str, JsonValue],
    *,
    dataset_id: str,
    source_id: str,
    contract_sha256: str,
    identity_semantics: Mapping[str, JsonValue],
    storage_order: list[JsonValue],
    schema_json: list[dict[str, JsonValue]],
    canonical_json_fn: Callable[[object], bytes],
    contract_from_page_fn: Callable[
        [Mapping[str, JsonValue], Mapping[str, JsonValue]], dict[str, JsonValue]
    ],
    valid_text_fn: Callable[..., bool],
    valid_identifier_fn: Callable[[object], bool],
    error_cls: type[Exception],
) -> None:
    """Validate pinned dataset contract fields, source, and quality summary."""
    top_meta = {
        key: value
        for key, value in page.items()
        if key not in {"meta", "rows", "count", "next_cursor", "has_more"}
    }
    if canonical_json_fn(snapshot_meta) != canonical_json_fn(top_meta):
        raise error_cls(_PROTOCOL_INVALID)
    if (
        page["dataset_id"] != dataset_id
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
        or canonical_json_fn(page["identity_semantics"]) != canonical_json_fn(identity_semantics)
        or canonical_json_fn(page["storage_order"]) != canonical_json_fn(storage_order)
        or snapshot["ordering_fields"] != ["instrument_id"]
        or canonical_json_fn(snapshot["storage_order"]) != canonical_json_fn(storage_order)
        or snapshot["identity_key_encoding"] != "canonical-json-array-v1"
        or canonical_json_fn(page["window"])
        != canonical_json_fn({"start": None, "end": None, "end_exclusive": True})
        or page["adjustment_basis"] != "not_applicable"
        or page["currency"] is not None
        or canonical_json_fn(page["field_units"]) != b"{}"
        or canonical_json_fn(page["field_currencies"]) != b"{}"
        or canonical_json_fn(page["field_adjustments"]) != b"{}"
        or canonical_json_fn(page["schema"]) != canonical_json_fn(schema_json)
    ):
        raise error_cls(_PROTOCOL_INVALID)

    source = page.get("source")
    if (
        not isinstance(source, dict)
        or set(source) != {"source_id", "source"}
        or source.get("source_id") != source_id
        or not valid_text_fn(source.get("source"), maximum=128)
        or str(source.get("source", "")).strip() == ""
    ):
        raise error_cls(_PROTOCOL_INVALID)
    contract = contract_from_page_fn(page, source)
    if (
        page.get("contract_sha256") != contract_sha256
        or _SHA256.fullmatch(str(page.get("contract_sha256"))) is None
        or hashlib.sha256(canonical_json_fn(contract)).hexdigest() != contract_sha256
    ):
        raise error_cls(_PROTOCOL_INVALID)
    quality = page.get("quality")
    if (
        not isinstance(quality, dict)
        or set(quality) != {"status", "report_id", "issue_count"}
        or quality.get("status") != "passed"
        or not valid_identifier_fn(quality.get("report_id"))
        or type(quality.get("issue_count")) is not int
        or quality.get("issue_count") != 0
    ):
        raise error_cls(_PROTOCOL_INVALID)


def validate_page_timestamps_and_cursor(
    page: Mapping[str, JsonValue],
    *,
    page_size_limit: int,
    max_rows_limit: int,
    now: datetime,
    parse_datetime_fn: Callable[[object], datetime],
    valid_date_only_fn: Callable[..., bool],
    valid_identifier_fn: Callable[[object], bool],
    valid_cursor_fn: Callable[[object], bool],
    error_cls: type[Exception],
) -> None:
    """Validate page sequence, digests, timestamps, row count, and cursor shape."""
    for name in ("publication_id", "snapshot_id"):
        if not valid_identifier_fn(page.get(name)):
            raise error_cls(_PROTOCOL_INVALID)
    sequence = page.get("sequence")
    if type(sequence) is not int or sequence < 1:
        raise error_cls(_PROTOCOL_INVALID)
    if type(page.get("page_size")) is not int or page["page_size"] != page_size_limit:
        raise error_cls(_PROTOCOL_INVALID)
    record_count = page.get("record_count")
    if type(record_count) is not int or record_count < 0:
        raise error_cls(_PROTOCOL_INVALID)
    if record_count > max_rows_limit:
        raise error_cls(_LIMIT_EXCEEDED)
    for name in ("selection_sha256", "content_sha256"):
        value = page.get(name)
        if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
            raise error_cls(_PROTOCOL_INVALID)
    as_of = parse_datetime_fn(page.get("as_of"))
    created_at = parse_datetime_fn(page.get("created_at"))
    expires_at = parse_datetime_fn(page.get("expires_at"))
    if (
        as_of > created_at
        or as_of > now
        or created_at > now
        or expires_at <= now
        or expires_at <= created_at
    ):
        raise error_cls(_PROTOCOL_INVALID)
    if not valid_date_only_fn(page.get("as_of"), allow_datetime=True):
        raise error_cls(_PROTOCOL_INVALID)
    page_rows = page.get("rows")
    count = page.get("count")
    has_more = page.get("has_more")
    cursor = page.get("next_cursor")
    if (
        not isinstance(page_rows, list)
        or type(count) is not int
        or count != len(page_rows)
        or count < 0
        or count > page_size_limit
        or type(has_more) is not bool
    ):
        raise error_cls(_PROTOCOL_INVALID)
    if has_more:
        if count != page_size_limit or not valid_cursor_fn(cursor):
            raise error_cls(_PROTOCOL_INVALID)
    elif cursor is not None:
        raise error_cls(_PROTOCOL_INVALID)


def validate_instrument_payload_dates(
    payload: Mapping[str, JsonValue],
    *,
    valid_date_only_fn: Callable[..., bool],
    valid_evidence_fn: Callable[[object], bool],
    error_cls: type[Exception],
) -> None:
    """Validate known start/delist dates, evidence references, and monotonic boundaries."""
    status_as_of = date.fromisoformat(str(payload["status_as_of"]))
    known_start = payload.get("known_start_date")
    delisted_on = payload.get("delisted_on")
    start_evidence = payload.get("start_evidence_ref")
    delist_evidence = payload.get("delist_evidence_ref")
    if known_start is not None and not valid_date_only_fn(known_start):
        raise error_cls(_PROTOCOL_INVALID)
    if delisted_on is not None and not valid_date_only_fn(delisted_on):
        raise error_cls(_PROTOCOL_INVALID)
    if start_evidence is not None and not valid_evidence_fn(start_evidence):
        raise error_cls(_PROTOCOL_INVALID)
    if delist_evidence is not None and not valid_evidence_fn(delist_evidence):
        raise error_cls(_PROTOCOL_INVALID)
    if payload["start_boundary_unknown"]:
        if known_start is not None or start_evidence is not None:
            raise error_cls(_PROTOCOL_INVALID)
    elif known_start is None or start_evidence is None:
        raise error_cls(_PROTOCOL_INVALID)
    if payload["status"] == "delisted":
        if delisted_on is None or delist_evidence is None:
            raise error_cls(_PROTOCOL_INVALID)
        if status_as_of < date.fromisoformat(str(delisted_on)):
            raise error_cls(_PROTOCOL_INVALID)
    elif delisted_on is not None or delist_evidence is not None:
        raise error_cls(_PROTOCOL_INVALID)
    if known_start is not None and delisted_on is not None:
        if date.fromisoformat(str(known_start)) > date.fromisoformat(str(delisted_on)):
            raise error_cls(_PROTOCOL_INVALID)


def validate_instrument_payload_aliases(
    aliases: Any,
    *,
    valid_identifier_fn: Callable[[object], bool],
    valid_evidence_fn: Callable[[object], bool],
    valid_date_only_fn: Callable[..., bool],
    error_cls: type[Exception],
) -> None:
    """Validate bounded instrument alias entries and `[valid_from, valid_through]` ordering."""
    if not isinstance(aliases, list) or len(aliases) > 16:
        raise error_cls(_PROTOCOL_INVALID)
    for alias in aliases:
        if not isinstance(alias, dict) or set(alias) != _ALIAS_KEYS:
            raise error_cls(_PROTOCOL_INVALID)
        if any(
            not valid_identifier_fn(alias.get(field)) for field in ("alias", "alias_version")
        ) or not valid_evidence_fn(alias.get("evidence_ref")):
            raise error_cls(_PROTOCOL_INVALID)
        valid_from = alias.get("valid_from")
        valid_through = alias.get("valid_through")
        if valid_from is not None and not valid_date_only_fn(valid_from):
            raise error_cls(_PROTOCOL_INVALID)
        if valid_through is not None and not valid_date_only_fn(valid_through):
            raise error_cls(_PROTOCOL_INVALID)
        if valid_from is not None and valid_through is not None:
            if date.fromisoformat(str(valid_from)) > date.fromisoformat(str(valid_through)):
                raise error_cls(_PROTOCOL_INVALID)
