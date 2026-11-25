"""Shared and decomposed validation helpers for Sina LRB and FZB snapshot readers."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from typing import Any


def validate_sina_snapshot_tail(
    snapshot: Mapping[str, Any],
    *,
    instrument_id: str,
    capture_id: str,
    page_size: int,
    max_rows: int,
    hash_fields: tuple[str, ...],
    sha256_re: re.Pattern[str],
    validate_timestamp_fn: Callable[..., datetime | None],
    error_cls: Callable[[str], Exception],
) -> None:
    """Validate snapshot window, selection, pagination limits, digests, and expiry timestamps."""
    window = snapshot.get("window")
    if (
        not isinstance(window, dict)
        or set(window) != {"start", "end", "end_exclusive"}
        or window.get("start") is not None
        or window.get("end") is not None
        or window.get("end_exclusive") is not True
    ):
        raise error_cls("snapshot_window_invalid")
    selection = snapshot.get("selection")
    if (
        not isinstance(selection, dict)
        or set(selection) != {"instrument_id", "capture_id"}
        or selection.get("instrument_id") != instrument_id
        or selection.get("capture_id") != capture_id
    ):
        raise error_cls("snapshot_selection_mismatch")
    if type(snapshot.get("page_size")) is not int or snapshot["page_size"] != page_size:
        raise error_cls("snapshot_metadata_invalid")
    if (
        type(snapshot.get("record_count")) is not int
        or not 0 <= snapshot["record_count"] <= max_rows
    ):
        raise error_cls("snapshot_row_limit_exceeded")
    for field in hash_fields:
        if type(snapshot.get(field)) is not str or sha256_re.fullmatch(snapshot[field]) is None:
            raise error_cls("snapshot_hash_invalid")
    validate_timestamp_fn(snapshot.get("as_of"), nullable=False)
    created_at = validate_timestamp_fn(snapshot.get("created_at"), nullable=False)
    expires_at = validate_timestamp_fn(snapshot.get("expires_at"), nullable=False)
    if created_at is None or expires_at is None or expires_at <= created_at:
        raise error_cls("snapshot_expiry_invalid")


def _validate_single_lrb_node(
    node: object,
    *,
    expected_id: int,
    node_count: int,
    context: bool,
    max_value_text: int,
    max_decimal_exponent: int,
    reference_names: set[str],
    node_references_fn: Callable[[list[object], int], list[int]],
    error_cls: Callable[[str], Exception],
) -> list[int]:
    if (
        not isinstance(node, dict)
        or node.get("id") != expected_id
        or type(node.get("id")) is not int
    ):
        raise error_cls("record_payload_invalid")
    kind = node.get("kind")
    if kind == "null" and set(node) == {"id", "kind"}:
        return []
    if kind in {"boolean", "integer", "string"} and set(node) == {"id", "kind", "value"}:
        scalar = node["value"]
        valid = (
            (kind == "boolean" and type(scalar) is bool)
            or (kind == "integer" and type(scalar) is int and len(str(scalar)) <= max_value_text)
            or (kind == "string" and type(scalar) is str and len(scalar) <= max_value_text)
        )
        if not valid:
            raise error_cls("record_payload_invalid")
        return []
    if kind == "decimal" and set(node) == {"id", "kind", "sign", "digits", "exponent"}:
        sign, digits, exponent = node["sign"], node["digits"], node["exponent"]
        if (
            type(sign) is not int
            or sign not in {0, 1}
            or type(digits) is not str
            or not digits
            or len(digits) > max_value_text
            or any(character not in "0123456789" for character in digits)
            or type(exponent) is not int
            or abs(exponent) > max_decimal_exponent
        ):
            raise error_cls("record_payload_invalid")
        return []
    if kind == "array" and set(node) == {"id", "kind", "items"}:
        items = node["items"]
        if type(items) is not list or len(items) > node_count:
            raise error_cls("record_payload_invalid")
        return node_references_fn(items, node_count)
    if kind == "object" and set(node) == {"id", "kind", "fields"}:
        fields = node["fields"]
        if type(fields) is not list or len(fields) > node_count:
            raise error_cls("record_payload_invalid")
        names: set[str] = set()
        refs: list[int] = []
        for pair in fields:
            if (
                type(pair) is not list
                or len(pair) != 2
                or type(pair[0]) is not str
                or len(pair[0]) > max_value_text
                or pair[0] in names
            ):
                raise error_cls("record_payload_invalid")
            names.add(pair[0])
            refs.extend(node_references_fn([pair[1]], node_count))
        return refs
    if kind == "reference" and context and set(node) == {"id", "kind", "name"}:
        name = node["name"]
        if name not in {"report_date", "report_list"} or name in reference_names:
            raise error_cls("record_payload_invalid")
        reference_names.add(name)
        return []
    raise error_cls("record_payload_invalid")


def _verify_lrb_tree_connectivity(
    edges: list[list[int]],
    root_id: int,
    node_count: int,
    error_cls: Callable[[str], Exception],
) -> None:
    visited: set[int] = set()
    active: set[int] = set()
    pending: list[tuple[int, bool, int]] = [(root_id, False, 0)]
    while pending:
        node_id, exiting, depth = pending.pop()
        if depth > 32:
            raise error_cls("record_payload_invalid")
        if exiting:
            active.discard(node_id)
            visited.add(node_id)
            continue
        if node_id in active or node_id in visited:
            raise error_cls("record_payload_invalid")
        active.add(node_id)
        pending.append((node_id, True, depth))
        pending.extend((child_id, False, depth + 1) for child_id in reversed(edges[node_id]))
    if len(visited) != node_count:
        raise error_cls("record_payload_invalid")


def validate_lrb_node_table(
    value: object,
    *,
    context: bool,
    response_encoding: str,
    max_nodes: int,
    max_value_text: int,
    max_decimal_exponent: int,
    node_references_fn: Callable[[list[object], int], list[int]],
    error_cls: Callable[[str], Exception],
) -> None:
    """Check the frozen LRB node-table wire envelope without decoding its values."""
    if not isinstance(value, dict) or set(value) != {"encoding", "root_id", "nodes"}:
        raise error_cls("record_payload_invalid")
    nodes = value.get("nodes")
    root_id = value.get("root_id")
    if (
        value.get("encoding") != response_encoding
        or type(nodes) is not list
        or not nodes
        or len(nodes) > max_nodes
        or type(root_id) is not int
        or not 0 <= root_id < len(nodes)
        or not isinstance(nodes[root_id], dict)
        or nodes[root_id].get("kind") != "object"
    ):
        raise error_cls("record_payload_invalid")
    edges: list[list[int]] = [[] for _node in nodes]
    reference_names: set[str] = set()
    for expected_id, node in enumerate(nodes):
        edges[expected_id] = _validate_single_lrb_node(
            node,
            expected_id=expected_id,
            node_count=len(nodes),
            context=context,
            max_value_text=max_value_text,
            max_decimal_exponent=max_decimal_exponent,
            reference_names=reference_names,
            node_references_fn=node_references_fn,
            error_cls=error_cls,
        )
    if context and reference_names != {"report_date", "report_list"}:
        raise error_cls("record_payload_invalid")
    _verify_lrb_tree_connectivity(edges, root_id, len(nodes), error_cls)


def validate_fzb_payload_header(
    payload: Mapping[str, Any],
    *,
    instrument_id: str,
    capture_id: str,
    expected_paper_code: str,
    iso_date_re: re.Pattern[str],
    valid_date_fn: Callable[[str], bool],
    validate_timestamp_fn: Callable[..., datetime | None],
    validate_scalar_object_fn: Callable[[object], None],
    error_cls: Callable[[str], Exception],
) -> None:
    """Validate FZB payload scope, temporal metadata, and scalar metadata dicts."""
    if (
        payload.get("instrument_id") != instrument_id
        or payload.get("capture_id") != capture_id
        or payload.get("statement_code") != "fzb"
    ):
        raise error_cls("record_payload_scope_mismatch")
    if (
        type(payload.get("report_period")) is not str
        or iso_date_re.fullmatch(payload["report_period"]) is None
        or not valid_date_fn(payload["report_period"])
        or type(payload.get("source_paper_code")) is not str
        or payload["source_paper_code"] != expected_paper_code
        or type(payload.get("published_on")) is not str
        or iso_date_re.fullmatch(payload["published_on"]) is None
        or not valid_date_fn(payload["published_on"])
        or payload.get("publication_precision") != "date"
        or type(payload.get("source_update_epoch_seconds")) is not int
        or payload["source_update_epoch_seconds"] <= 0
        or type(payload.get("source_updated_at_timezone")) is not str
        or payload["source_updated_at_timezone"] != "Asia/Shanghai"
        or type(payload.get("currency")) is not str
        or not payload["currency"]
    ):
        raise error_cls("record_payload_invalid")
    source_updated_at = validate_timestamp_fn(payload.get("source_updated_at"), nullable=False)
    retrieved_at_utc = validate_timestamp_fn(payload.get("retrieved_at_utc"), nullable=False)
    if (
        source_updated_at is None
        or source_updated_at.utcoffset() != timedelta(hours=8)
        or retrieved_at_utc is None
        or retrieved_at_utc.utcoffset() != timedelta(0)
        or not str(payload["retrieved_at_utc"]).endswith("Z")
    ):
        raise error_cls("record_payload_invalid")
    try:
        source_update_epoch = datetime.fromtimestamp(
            payload["source_update_epoch_seconds"], tz=timezone.utc
        )
    except (OverflowError, OSError, ValueError):
        raise error_cls("record_payload_invalid") from None
    if source_update_epoch.astimezone(source_updated_at.tzinfo) != source_updated_at:
        raise error_cls("record_payload_invalid")
    for field in ("period_metadata", "report_metadata"):
        validate_scalar_object_fn(payload.get(field))


_FZB_ITEM_FIELDS = frozenset(
    {
        "kind",
        "source_item_id",
        "source_title",
        "source_ordinals",
        "raw_value",
        "value_state",
        "source_metadata",
    }
)
_FZB_GROUP_FIELDS = frozenset(
    {
        "kind",
        "source_ordinals",
        "source_group_no",
        "source_title",
        "raw_item_field",
        "raw_item_value",
        "source_metadata",
    }
)


def validate_fzb_entry(
    entry: object,
    *,
    max_report_entries: int,
    previous_first_ordinal: int,
    validate_scalar_object_fn: Callable[[object], None],
    error_cls: Callable[[str], Exception],
) -> tuple[int, list[int]]:
    """Validate one FZB report entry dict and return `(next_first_ordinal, ordinals)`."""
    if not isinstance(entry, dict):
        raise error_cls("record_entry_invalid")
    kind = entry.get("kind")
    if kind == "item":
        if (
            set(entry) != _FZB_ITEM_FIELDS
            or type(entry.get("source_item_id")) is not str
            or not entry["source_item_id"]
            or type(entry.get("source_title")) is not str
            or not entry["source_title"]
            or (entry.get("raw_value") is not None and type(entry["raw_value"]) is not str)
        ):
            raise error_cls("record_entry_invalid")
        expected_state = (
            "null"
            if entry["raw_value"] is None
            else "empty"
            if entry["raw_value"] == ""
            else "present"
        )
        if entry.get("value_state") != expected_state:
            raise error_cls("record_entry_invalid")
    elif kind == "group_marker":
        if (
            set(entry) != _FZB_GROUP_FIELDS
            or type(entry.get("source_group_no")) is not int
            or entry["source_group_no"] not in {1, 2, 3, 4, 5}
            or type(entry.get("source_title")) is not str
            or not entry["source_title"]
            or entry.get("raw_item_field") != ""
            or entry.get("raw_item_value") != ""
        ):
            raise error_cls("record_entry_invalid")
    else:
        raise error_cls("record_entry_invalid")
    validate_scalar_object_fn(entry.get("source_metadata"))
    ordinals = entry.get("source_ordinals")
    if (
        not isinstance(ordinals, list)
        or not ordinals
        or len(ordinals) > max_report_entries
        or any(type(value) is not int or value < 0 for value in ordinals)
        or any(left >= right for left, right in zip(ordinals, ordinals[1:], strict=False))
        or ordinals[0] <= previous_first_ordinal
    ):
        raise error_cls("record_ordinals_invalid")
    return ordinals[0], ordinals
