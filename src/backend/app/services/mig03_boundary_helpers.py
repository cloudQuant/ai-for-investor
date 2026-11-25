"""Validation and builder helpers decomposed from MIG03 boundary inventory."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any
from typing import cast as typing_cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.paper_runtime import PaperEquitySnapshot

CODE_INVALID_BOUNDARY_SCOPE = "AFI_MIG03_INVALID_BOUNDARY_SCOPE"
CODE_BOUNDARY_READ_FAILED = "AFI_MIG03_BOUNDARY_READ_FAILED"
CODE_BOUNDARY_NOT_CONSERVED = "AFI_MIG03_BOUNDARY_NOT_CONSERVED"
CODE_WRITER_STILL_ACTIVE = "AFI_MIG03_WRITER_STILL_ACTIVE"

_LEGACY_IMPORT_CONTEXT_CATEGORIES = frozenset(
    {
        "risk_rules",
        "alerts",
        "alert_rules",
        "alert_notifications",
        "strategy_target_approvals",
        "strategy_target_approval_events",
        "strategy_order_approval_policy_versions",
        "strategy_order_approval_policy_heads",
        "strategy_approval_authority_epoch",
        "paper_review_reports",
        "live_handoff_reviews",
        "paper_equity_snapshots",
    }
)
_LEGACY_IMPORT_CURSOR_CONTRACT = {
    "legacy_cursor_format": "base64url_json_observed_at_id",
    "legacy_cursor_retained": "stateless_runtime_source_only",
    "target_cursor_activated": False,
}


class AfiMigrationBoundaryError(RuntimeError):
    """Finite AFI MIG03 inventory error without account data."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class AfiConfiguredSnapshotWriter:
    """One production-restorable AFI paper snapshot writer and its owner link.

    The external ``account_ref`` is supplied by the typed migration mapping;
    this inventory proves only that the AFI runtime's persisted snapshot rows
    all point to one real ``paper_trading_accounts.id`` owned by the workspace
    user. It never derives either identity from a similarly named string.
    """

    consumer_id: str
    consumer_kind: str
    configuration_sha256: str
    scope_sha256: str
    operations_sha256: str
    account_ref: str
    paper_account_id: str
    user_id: str
    workspace_id: str
    unit_id: str
    instance_id: str


def canonical_json(value: Any) -> bytes:
    """Encode a JSON-serializable structure canonically as UTF-8 bytes."""
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8", errors="strict")
    except (TypeError, ValueError, UnicodeError):
        raise AfiMigrationBoundaryError(CODE_BOUNDARY_READ_FAILED) from None


def text_set(values: Iterable[str], *, max_rows: int) -> tuple[str, ...]:
    """Validate and sort a bounded unique sequence of non-empty text identifiers."""
    if type(values) not in (tuple, list):
        raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE) from None
    sized_values = typing_cast("Collection[str]", values)
    if len(sized_values) > max_rows:
        raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE) from None
    if any(type(value) is not str or not value for value in sized_values) or len(
        set(sized_values)
    ) != len(sized_values):
        raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)
    return tuple(sorted(sized_values))


def require_text(value: Any) -> None:
    """Require one non-empty string value."""
    if type(value) is not str or not value:
        raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)


def valid_sha256(value: Any) -> bool:
    """Return whether ``value`` is a 64-char lowercase hex SHA-256 string."""
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def require_sha256(value: Any) -> None:
    """Require one valid 64-char lowercase hex SHA-256 string."""
    if not valid_sha256(value):
        raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)


def _require_non_empty_string_dict(mapping: object) -> None:
    if type(mapping) is not dict:
        raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)
    if any(type(key) is not str or not key for key in mapping):
        raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)
    if any(type(val) is not str or not val for val in mapping.values()):
        raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)


def validate_capture_inputs(
    session: Session,
    *,
    scope_ref: str,
    account_ref: str,
    strategy_refs: Iterable[str],
    account_paper_accounts: dict[str, str],
    paper_account_instances: dict[str, str],
    source_ref: str,
    configuration_sha256: str,
    max_rows: int,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Validate read-only session cleanliness and explicit scope parameters."""
    if (
        not isinstance(session, Session)
        or not session.is_active
        or session.new
        or session.dirty
        or session.deleted
    ):
        raise AfiMigrationBoundaryError(CODE_BOUNDARY_READ_FAILED)
    require_text(scope_ref)
    require_text(account_ref)
    require_text(source_ref)
    require_sha256(configuration_sha256)
    strategy_values = text_set(strategy_refs, max_rows=max_rows)
    _require_non_empty_string_dict(account_paper_accounts)
    _require_non_empty_string_dict(paper_account_instances)
    account_values = tuple(sorted(paper_account_instances))
    instance_values = tuple(sorted(set(paper_account_instances.values())))
    if (
        not strategy_values
        or not account_values
        or len(account_values) != 1
        or not instance_values
        or account_paper_accounts != {account_ref: account_values[0]}
    ):
        raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)
    return strategy_values, account_values, instance_values


def validate_writer_enumeration_inputs(
    session: Session,
    account_refs_by_paper_account: Mapping[str, str],
    configuration_sha256: str,
) -> None:
    """Validate session cleanliness and unique non-empty account crosswalk mappings."""
    if (
        not isinstance(session, Session)
        or not session.is_active
        or session.new
        or session.dirty
        or session.deleted
        or type(account_refs_by_paper_account) is not dict
    ):
        raise AfiMigrationBoundaryError(CODE_BOUNDARY_READ_FAILED)
    require_sha256(configuration_sha256)
    if any(
        type(account_id) is not str
        or not account_id
        or type(account_ref) is not str
        or not account_ref
        for account_id, account_ref in account_refs_by_paper_account.items()
    ):
        raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)
    if len(set(account_refs_by_paper_account.values())) != len(account_refs_by_paper_account):
        raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)


def collect_writer_instance_selections(
    session: Session,
    configured_rows: list[Any],
    *,
    max_rows: int,
    max_bytes: int,
) -> tuple[list[dict[str, Any]], set[str]]:
    """Verify per-instance historical snapshot rows and derive account ownership links."""
    selected: list[dict[str, Any]] = []
    all_account_ids: set[str] = set()
    seen_instances: set[str] = set()
    snapshot_bytes = 0
    snapshot_rows_seen = 0
    for configured in configured_rows:
        workspace_id = configured.workspace_id
        user_id = configured.user_id
        unit_id = configured.unit_id
        instance_id = configured.instance_id
        if (
            any(
                type(val) is not str or not val
                for val in (workspace_id, user_id, unit_id, instance_id)
            )
            or configured.unit_workspace_id != workspace_id
            or instance_id in seen_instances
        ):
            raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)
        seen_instances.add(instance_id)
        rows = list(
            session.execute(
                select(
                    PaperEquitySnapshot.id,
                    PaperEquitySnapshot.user_id,
                    PaperEquitySnapshot.workspace_id,
                    PaperEquitySnapshot.unit_id,
                    PaperEquitySnapshot.instance_id,
                    PaperEquitySnapshot.paper_account_id,
                )
                .where(PaperEquitySnapshot.instance_id == instance_id)
                .order_by(PaperEquitySnapshot.id)
                .limit(max_rows + 1)
            ).all()
        )
        if not rows or len(rows) > max_rows:
            raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)
        accounts_for_instance: set[str] = set()
        for row in rows:
            identity = tuple(row)
            encoded = canonical_json(identity)
            snapshot_bytes += len(encoded)
            snapshot_rows_seen += 1
            if snapshot_rows_seen > max_rows or snapshot_bytes > max_bytes:
                raise AfiMigrationBoundaryError(CODE_BOUNDARY_READ_FAILED)
            snapshot_id, snap_user, snap_ws, snap_unit, snap_inst, paper_account_id = identity
            if (
                type(snapshot_id) is not str
                or not snapshot_id
                or (snap_user, snap_ws, snap_unit, snap_inst)
                != (user_id, workspace_id, unit_id, instance_id)
                or type(paper_account_id) is not str
                or not paper_account_id
            ):
                raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)
            accounts_for_instance.add(paper_account_id)
        if len(accounts_for_instance) != 1:
            raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)
        paper_account_id = next(iter(accounts_for_instance))
        all_account_ids.add(paper_account_id)
        selected.append(
            {
                "user_id": user_id,
                "workspace_id": workspace_id,
                "unit_id": unit_id,
                "instance_id": instance_id,
                "paper_account_id": paper_account_id,
            }
        )
    return selected, all_account_ids


def build_configured_snapshot_writers(
    selected: list[dict[str, Any]],
    account_refs_by_paper_account: Mapping[str, str],
    account_by_id: Mapping[str, dict[str, Any]],
    workspaces: Mapping[str, dict[str, Any]],
    units: Mapping[str, dict[str, Any]],
    configuration_sha256: str,
) -> tuple[AfiConfiguredSnapshotWriter, ...]:
    """Construct verified immutable snapshot writer descriptors ordered by consumer ID."""
    consumers: list[AfiConfiguredSnapshotWriter] = []
    operations = {"model": "PaperEquitySnapshot", "operation": "scheduled_snapshot"}
    operations_sha256 = hashlib.sha256(canonical_json(operations)).hexdigest()
    for item in selected:
        account_id = item["paper_account_id"]
        if account_by_id[account_id]["user_id"] != item["user_id"]:
            raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)
        account_ref = account_refs_by_paper_account[account_id]
        scope_document = {
            "account_ref": account_ref,
            "user_id": item["user_id"],
            "workspace_id": item["workspace_id"],
            "unit_id": item["unit_id"],
            "instance_id": item["instance_id"],
        }
        configuration_document = {
            "configuration_sha256": configuration_sha256,
            "consumer_kind": "afi_snapshot_scheduler",
            "scheduler": (
                "app.services.paper_runtime_scheduler.PaperRuntimeSnapshotScheduler.start_existing"
            ),
            "workspace": workspaces[item["workspace_id"]],
            "strategy_unit": units[item["unit_id"]],
            "verified_account_fk": account_id,
            "account_ref_crosswalk": account_ref,
        }
        configuration_digest = hashlib.sha256(canonical_json(configuration_document)).hexdigest()
        scope_digest = hashlib.sha256(canonical_json(scope_document)).hexdigest()
        consumers.append(
            AfiConfiguredSnapshotWriter(
                consumer_id="afi-snapshot-writer-v1:" + configuration_digest,
                consumer_kind="afi_snapshot_scheduler",
                configuration_sha256=configuration_digest,
                scope_sha256=scope_digest,
                operations_sha256=operations_sha256,
                account_ref=account_ref,
                paper_account_id=account_id,
                user_id=item["user_id"],
                workspace_id=item["workspace_id"],
                unit_id=item["unit_id"],
                instance_id=item["instance_id"],
            )
        )
    return tuple(sorted(consumers, key=lambda item: item.consumer_id))


def _group_events_by_approval(
    events: tuple[dict[str, Any], ...],
) -> dict[str, list[dict[str, Any]]]:
    events_by_ref: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        if (
            type(event.get("record_version")) is not int
            or event["record_version"] < 1
            or type(event.get("approval_version")) is not int
        ):
            raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)
        events_by_ref.setdefault(event["approval_ref"], []).append(event)
    return events_by_ref


def _validate_single_approval_chain(
    approval: dict[str, Any],
    approval_events: list[dict[str, Any]],
) -> None:
    record_version = approval["record_version"]
    if (
        type(record_version) is not int
        or record_version < 1
        or not approval_events
        or [row["record_version"] for row in approval_events] != list(range(1, record_version + 1))
        or any(row["approval_version"] != approval["approval_version"] for row in approval_events)
        or any(row["owner_subject"] != approval["owner_subject"] for row in approval_events)
        or any(row["target_sha256"] != approval["target_sha256"] for row in approval_events)
    ):
        raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)

    event_types = tuple(row["event_type"] for row in approval_events)
    if (
        event_types[0] != "APPROVED"
        or any(
            event_type not in {"APPROVED", "OPERATION_RESERVED", "REVOKED", "CONSUMED"}
            for event_type in event_types
        )
        or event_types.count("APPROVED") != 1
    ):
        raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)

    reserved_events = [row for row in approval_events if row["event_type"] == "OPERATION_RESERVED"]
    reservation_values = tuple(
        approval[field]
        for field in (
            "operation_key_sha256",
            "operation_request_sha256",
            "intent_id",
            "operation_reserved_at_ns",
        )
    )
    has_reserved_operation = all(value is not None for value in reservation_values)
    if any(value is None for value in reservation_values) and any(
        value is not None for value in reservation_values
    ):
        raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)
    if len(reserved_events) != int(has_reserved_operation) or any(
        row["intent_id"] != approval["intent_id"]
        or row["operation_key_sha256"] != approval["operation_key_sha256"]
        or row["occurred_at_ns"] != approval["operation_reserved_at_ns"]
        for row in reserved_events
    ):
        raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)

    expected_prefix = ("APPROVED",) + (("OPERATION_RESERVED",) if has_reserved_operation else ())
    state = approval["state"]
    expected_sequences = {
        "APPROVED": {expected_prefix},
        "REVOKED": {(*expected_prefix, "REVOKED")},
        "CONSUMED": {(*expected_prefix, "CONSUMED")},
    }.get(state)
    if expected_sequences is None or event_types not in expected_sequences:
        raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)

    approved_event = approval_events[0]
    if any(
        approved_event[event_field] != approval[approval_field]
        for event_field, approval_field in (
            ("owner_subject", "owner_subject"),
            ("actor_subject", "approved_by_subject"),
            ("principal_ref", "approved_by_principal_ref"),
            ("actor_ref", "approved_by_actor_ref"),
            ("delegate_ref", "approved_by_delegate_ref"),
            ("occurred_at_ns", "approved_at_ns"),
        )
    ):
        raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)

    if state == "REVOKED":
        revoked_event = approval_events[-1]
        if any(
            revoked_event[event_field] != approval[approval_field]
            for event_field, approval_field in (
                ("actor_subject", "revoked_by_subject"),
                ("actor_ref", "revoked_by_actor_ref"),
                ("reason_code", "revocation_reason_code"),
                ("occurred_at_ns", "revoked_at_ns"),
            )
        ):
            raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)
    elif state == "CONSUMED":
        consumed_event = approval_events[-1]
        if (
            approval["consumed_record_version"] != approval["record_version"]
            or consumed_event["record_version"] != approval["consumed_record_version"]
            or consumed_event["intent_id"] != approval["intent_id"]
            or consumed_event["operation_key_sha256"] != approval["operation_key_sha256"]
            or consumed_event["intent_sha256"] != approval["consumed_intent_sha256"]
            or consumed_event["consumption_ref"] != approval["consumption_ref"]
            or consumed_event["occurred_at_ns"] != approval["consumed_at_ns"]
        ):
            raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)


def validate_approval_event_chains(
    approvals: tuple[dict[str, Any], ...],
    events: tuple[dict[str, Any], ...],
) -> None:
    """Verify event sequence integrity for every persisted strategy target approval."""
    events_by_ref = _group_events_by_approval(events)
    for approval in approvals:
        if type(approval.get("approval_version")) is not int:
            raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)
        approval_events = sorted(
            events_by_ref.get(approval["approval_ref"], ()),
            key=lambda row: row["record_version"],
        )
        _validate_single_approval_chain(approval, approval_events)


_RECEIPT_STRING_FIELDS = (
    "id",
    "legacy_account_id",
    "owner_subject",
    "state",
    "source_inventory_sha256",
    "target_import_sha256",
    "target_domain_sha256",
    "binding_sha256",
    "target_scope_key",
    "target_account_key",
    "cash_currency",
    "opening_cash",
    "cumulative_fees",
    "unallocated_equity_residual",
    "preserved_context_sha256",
)
_RECEIPT_SHA256_FIELDS = (
    "source_inventory_sha256",
    "target_import_sha256",
    "target_domain_sha256",
    "binding_sha256",
    "preserved_context_sha256",
)


def _validate_receipt_scalars(
    row: dict[str, Any],
    users_by_account: Mapping[str, str],
    account_values: tuple[str, ...],
    generations: set[tuple[str, int]],
    active_accounts: set[str],
) -> str:
    if any(type(row.get(field)) is not str or not row[field] for field in _RECEIPT_STRING_FIELDS):
        raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)
    account_id = row["legacy_account_id"]
    state = row["state"]
    if (
        account_id not in account_values
        or row.get("owner_subject") != users_by_account.get(account_id)
        or type(row.get("receipt_version")) is not int
        or row["receipt_version"] != 1
        or type(row.get("generation")) is not int
        or row["generation"] < 1
        or any(
            type(row.get(field)) is not int or row[field] < 0
            for field in ("source_order_count", "source_position_count", "source_trade_count")
        )
        or any(not valid_sha256(row[field]) for field in _RECEIPT_SHA256_FIELDS)
    ):
        raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)
    generation_key = (account_id, row["generation"])
    if generation_key in generations:
        raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)
    generations.add(generation_key)
    active_fence_key = row.get("active_fence_key")
    if state in {"PREPARED", "COMMITTED", "ACTIVE"}:
        if active_fence_key != account_id or account_id in active_accounts:
            raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)
        active_accounts.add(account_id)
    elif state == "ABORTED":
        if active_fence_key is not None:
            raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)
    else:
        raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)
    return account_id


def _parse_and_verify_receipt_documents(row: dict[str, Any], account_id: str) -> dict[str, Any]:
    source_json = row.get("source_snapshot_json")
    context_json = row.get("preserved_context_json")
    try:
        if type(source_json) is not str or type(context_json) is not str:
            raise ValueError("invalid receipt payload type")
        source_bytes = source_json.encode("utf-8")
        context_bytes = context_json.encode("utf-8")
        if len(context_bytes) > 8 * 1024 * 1024:
            raise ValueError("preserved context exceeds producer limit")
        source_document = json.loads(source_json)
        context_document = json.loads(context_json)
        if (
            canonical_json(source_document) != source_bytes
            or hashlib.sha256(source_bytes).hexdigest() != row["source_inventory_sha256"]
            or canonical_json(context_document) != context_bytes
            or hashlib.sha256(context_bytes).hexdigest() != row["preserved_context_sha256"]
        ):
            raise ValueError("non-canonical receipt payload")
    except (RecursionError, TypeError, ValueError, UnicodeError):
        raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE) from None
    if (
        type(source_document) is not dict
        or set(source_document) != {"schema", "account", "orders", "positions", "trades"}
        or source_document.get("schema") != "afi.legacy-paper-inventory.v1"
        or type(source_document.get("account")) is not dict
        or source_document["account"].get("id") != account_id
        or source_document["account"].get("user_id") != row["owner_subject"]
        or type(context_document) is not dict
        or context_document.get("schema") != "afi.legacy-paper-preserved-context.v1"
        or context_document.get("source_account_id") != account_id
        or context_document.get("owner_subject") != row["owner_subject"]
        or context_document.get("activation") != "retained_in_legacy_source_only"
        or context_document.get("cursor_contract") != _LEGACY_IMPORT_CURSOR_CONTRACT
        or type(context_document.get("categories")) is not dict
        or set(context_document["categories"]) != _LEGACY_IMPORT_CONTEXT_CATEGORIES
        or any(
            type(category_rows) is not list
            or any(type(category_row) is not dict for category_row in category_rows)
            for category_rows in context_document["categories"].values()
        )
    ):
        raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)
    return source_document


def _validate_receipt_source_counts_and_decimals(
    row: dict[str, Any], source_document: dict[str, Any], account_id: str
) -> None:
    for name, count_field in (
        ("orders", "source_order_count"),
        ("positions", "source_position_count"),
        ("trades", "source_trade_count"),
    ):
        source_rows = source_document.get(name)
        if type(source_rows) is not list or len(source_rows) != row[count_field]:
            raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)
        row_ids: set[str] = set()
        for source_row in source_rows:
            if (
                type(source_row) is not dict
                or source_row.get("account_id") != account_id
                or type(source_row.get("id")) is not str
                or not source_row["id"]
                or source_row["id"] in row_ids
            ):
                raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)
            row_ids.add(source_row["id"])
    for field in ("opening_cash", "cumulative_fees", "unallocated_equity_residual"):
        value = row.get(field)
        if type(value) is not str:
            raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)
        try:
            decimal_value = Decimal(value)
        except (InvalidOperation, ValueError):
            raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE) from None
        if not decimal_value.is_finite():
            raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)


def validate_import_receipts(
    receipts: tuple[dict[str, Any], ...],
    accounts: tuple[dict[str, Any], ...],
    account_values: tuple[str, ...],
) -> None:
    """Validate AFI12 source-side handoff receipts before inventorying them."""
    users_by_account = {row["id"]: row["user_id"] for row in accounts}
    generations: set[tuple[str, int]] = set()
    active_accounts: set[str] = set()
    for row in receipts:
        account_id = _validate_receipt_scalars(
            row, users_by_account, account_values, generations, active_accounts
        )
        source_document = _parse_and_verify_receipt_documents(row, account_id)
        _validate_receipt_source_counts_and_decimals(row, source_document, account_id)
