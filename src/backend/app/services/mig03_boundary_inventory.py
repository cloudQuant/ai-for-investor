"""Read-only MIG03 inventory for AFI operation and paper-account state.

The SDK migration gate owns deployment epochs.  This module records the AFI
facts that must accompany that gate: HTTP idempotency and approval links, plus
the existing paper account, order, fill, fee, position, and equity snapshot
rows, including AFI12 legacy-import receipts. It never imports, rewrites, or
deletes those rows; the accepted MIG03 path retains the same database in place.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping

from sqlalchemy import JSON, LargeBinary, String, Text, cast, func, select
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session

from app.models.approved_target_http_operation import ApprovedTargetHttpOperation
from app.models.legacy_paper_import import LegacyPaperImportReceipt
from app.models.paper_runtime import PaperEquitySnapshot
from app.models.paper_trading import Account, Order, PaperTrade, Position
from app.models.workspace import StrategyUnit, Workspace
from app.models.service_order_operation import ServiceOrderOperation
from app.models.strategy_target_approval import (
    StrategyTargetApproval,
    StrategyTargetApprovalEvent,
)
from app.services.paper_runtime_scheduler import PaperRuntimeSnapshotScheduler

CODE_INVALID_BOUNDARY_SCOPE = "AFI_MIG03_INVALID_BOUNDARY_SCOPE"
CODE_BOUNDARY_READ_FAILED = "AFI_MIG03_BOUNDARY_READ_FAILED"
CODE_BOUNDARY_NOT_CONSERVED = "AFI_MIG03_BOUNDARY_NOT_CONSERVED"
CODE_WRITER_STILL_ACTIVE = "AFI_MIG03_WRITER_STILL_ACTIVE"

_SCHEDULER_STOP_TIMEOUT_SECONDS = 5.0
_PAPER_TERMINAL_STATES = frozenset({"filled", "cancelled", "rejected"})
_MAX_BOUNDARY_ROWS = 100_000
_MAX_BOUNDARY_BYTES = 32 * 1024 * 1024
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
class AfiParticipantFacts:
    """State digest and ID links for one AFI inventory category."""

    participant_id: str
    source_ref: str
    state_sha256: str
    identity_sha256: str
    schema_sha256: str
    row_count: int


@dataclass(frozen=True, slots=True)
class AfiBoundarySnapshot:
    """Closed projection of operation, approval, and paper-ledger state."""

    scope_ref: str
    account_ref: str
    strategy_refs: tuple[str, ...]
    paper_account_ids: tuple[str, ...]
    paper_instance_ids: tuple[str, ...]
    operation_approval: AfiParticipantFacts
    paper_ledger: AfiParticipantFacts
    identity_links: tuple[tuple[str, str, str, str], ...]
    amounts: tuple[tuple[str, str], ...]
    positions: tuple[tuple[str, str], ...]
    unresolved_ids: tuple[str, ...]
    reservation_ids: tuple[str, ...]

    def boundary_participants(self) -> tuple[dict[str, Any], dict[str, Any]]:
        """Return fixed-schema dictionaries accepted by the SDK boundary gate."""

        return tuple(
            {
                "participant_id": fact.participant_id,
                "source_ref": fact.source_ref,
                "configuration_sha256": self._configuration_sha256,
                "state_sha256": fact.state_sha256,
                "identity_sha256": fact.identity_sha256,
                "schema_sha256": fact.schema_sha256,
                "row_count": fact.row_count,
            }
            for fact in (self.operation_approval, self.paper_ledger)
        )  # type: ignore[return-value]

    _configuration_sha256: str = ""


@dataclass(frozen=True, slots=True)
class PaperWriterStopReceipt:
    """Bounded stop observation for AFI's process-local paper snapshot workers."""

    scheduler_type: str
    tasks_before: int
    stopped_task_names: tuple[str, ...]
    tasks_after: int


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


@dataclass(slots=True)
class _InventoryReadBudget:
    rows: int = 0
    bytes: int = 0


def capture_afi_boundary(
    session: Session,
    *,
    scope_ref: str,
    account_ref: str,
    strategy_refs: Iterable[str],
    account_paper_accounts: dict[str, str],
    paper_account_instances: dict[str, str],
    source_ref: str,
    configuration_sha256: str,
) -> AfiBoundarySnapshot:
    """Read a complete scoped AFI operation/approval/paper inventory.

    All scope keys are explicit.  This function does not infer account,
    strategy, paper account, or runtime relationships from similarly named
    strings.  Queries include the original operation/approval references and
    every paper order/fill/position/snapshot row for the provided accounts.
    """

    if (
        not isinstance(session, Session)
        or not session.is_active
        or session.new
        or session.dirty
        or session.deleted
    ):
        raise AfiMigrationBoundaryError(CODE_BOUNDARY_READ_FAILED)
    _require_text(scope_ref)
    _require_text(account_ref)
    _require_text(source_ref)
    _require_sha256(configuration_sha256)
    strategy_values = _text_set(strategy_refs)
    if type(account_paper_accounts) is not dict:
        raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)
    if any(type(key) is not str or not key for key in account_paper_accounts):
        raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)
    if any(type(value) is not str or not value for value in account_paper_accounts.values()):
        raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)
    if type(paper_account_instances) is not dict:
        raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)
    if any(type(key) is not str or not key for key in paper_account_instances):
        raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)
    if any(type(value) is not str or not value for value in paper_account_instances.values()):
        raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)
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

    budget = _InventoryReadBudget()
    try:
        operations = _query_rows(
            session,
            ServiceOrderOperation,
            select(ServiceOrderOperation).where(
                ServiceOrderOperation.scope_ref == scope_ref,
                ServiceOrderOperation.account_ref == account_ref,
            ),
            budget,
        )
        approved_http_operations = _query_rows(
            session,
            ApprovedTargetHttpOperation,
            select(ApprovedTargetHttpOperation).where(
                ApprovedTargetHttpOperation.scope_ref == scope_ref,
                ApprovedTargetHttpOperation.account_ref == account_ref,
                ApprovedTargetHttpOperation.strategy_ref.in_(strategy_values),
            ),
            budget,
        )
        approvals = _query_rows(
            session,
            StrategyTargetApproval,
            select(StrategyTargetApproval).where(
                StrategyTargetApproval.scope_ref == scope_ref,
                StrategyTargetApproval.account_ref == account_ref,
                StrategyTargetApproval.strategy_ref.in_(strategy_values),
            ),
            budget,
        )
        approval_refs = tuple(row["approval_ref"] for row in approvals)
        approval_events = (
            _query_rows(
                session,
                StrategyTargetApprovalEvent,
                select(StrategyTargetApprovalEvent).where(
                    StrategyTargetApprovalEvent.approval_ref.in_(approval_refs)
                ),
                budget,
            )
            if approval_refs
            else ()
        )

        accounts = _query_rows(
            session,
            Account,
            select(Account).where(Account.id.in_(account_values)),
            budget,
        )
        requested_users = tuple(sorted({row["user_id"] for row in accounts}))
        if not requested_users or any(type(value) is not str or not value for value in requested_users):
            raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)
        all_user_accounts = _query_rows(
            session,
            Account,
            select(Account).where(Account.user_id.in_(requested_users)),
            budget,
        )
        positions = _query_rows(
            session,
            Position,
            select(Position).where(Position.account_id.in_(account_values)),
            budget,
        )
        orders = _query_rows(
            session,
            Order,
            select(Order).where(Order.account_id.in_(account_values)),
            budget,
        )
        trades = _query_rows(
            session,
            PaperTrade,
            select(PaperTrade).where(PaperTrade.account_id.in_(account_values)),
            budget,
        )
        snapshots = _query_rows(
            session,
            PaperEquitySnapshot,
            select(PaperEquitySnapshot).where(
                (PaperEquitySnapshot.instance_id.in_(instance_values))
                | (PaperEquitySnapshot.paper_account_id.in_(account_values))
                | (PaperEquitySnapshot.user_id.in_(requested_users))
            ),
            budget,
        )
        import_receipts = _query_rows(
            session,
            LegacyPaperImportReceipt,
            select(LegacyPaperImportReceipt).where(
                LegacyPaperImportReceipt.legacy_account_id.in_(account_values)
            ),
            budget,
        )
    except AfiMigrationBoundaryError:
        raise
    except Exception:
        raise AfiMigrationBoundaryError(CODE_BOUNDARY_READ_FAILED) from None

    requested_accounts = set(account_values)
    if {row["id"] for row in accounts} != requested_accounts:
        raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)
    if {row["id"] for row in all_user_accounts} != requested_accounts:
        raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)
    if any(row["account_id"] not in requested_accounts for row in (*positions, *orders, *trades)):
        raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)
    if any(
        row["paper_account_id"] is None
        or paper_account_instances.get(row["paper_account_id"]) != row["instance_id"]
        for row in snapshots
    ):
        raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)
    paper_user_by_account = {row["id"]: row["user_id"] for row in accounts}
    if any(
        row["user_id"] != paper_user_by_account.get(row["paper_account_id"])
        for row in snapshots
    ):
        raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)
    _validate_import_receipts(import_receipts, accounts, account_values)
    approvals_by_ref = {row["approval_ref"]: row for row in approvals}
    if any(
        row["approval_ref"] not in approvals_by_ref
        or not _http_operation_matches_approval(row, approvals_by_ref[row["approval_ref"]])
        for row in approved_http_operations
    ):
        raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)
    _validate_identity_fields(
        operations,
        approved_http_operations,
        approvals,
        approval_events,
        accounts,
        positions,
        orders,
        trades,
        snapshots,
        import_receipts,
    )
    _validate_approval_event_chains(approvals, approval_events)

    operation_rows = (
        ("service_order_operations", operations),
        ("approved_target_http_operations", approved_http_operations),
        ("strategy_target_approvals", approvals),
        ("strategy_target_approval_events", approval_events),
    )
    paper_rows = (
        ("paper_trading_accounts", accounts),
        ("paper_trading_positions", positions),
        ("paper_trading_orders", orders),
        ("paper_trades", trades),
        ("paper_equity_snapshots", snapshots),
        ("legacy_paper_import_receipts", import_receipts),
    )
    identity_links = _identity_links(
        account_ref,
        account_values[0],
        operations,
        approved_http_operations,
        approvals,
        approval_events,
        accounts,
        positions,
        orders,
        trades,
        snapshots,
        import_receipts,
    )
    amounts = _financial_amounts(
        accounts, positions, orders, trades, snapshots, import_receipts
    )
    position_amounts = _position_amounts(positions)
    unresolved_ids = tuple(
        sorted(
            row["id"]
            for row in orders
            if type(row["status"]) is not str
            or row["status"].lower() not in _PAPER_TERMINAL_STATES
        )
    )
    reservation_ids = tuple(
        sorted(
            {
                row["intent_id"]
                for row in operations
                if row["intent_id"]
            }
            | {
                row["intent_id"]
                for row in approved_http_operations
                if row["intent_id"]
            }
            | {
                row["intent_id"]
                for row in approvals
                if row["intent_id"]
            }
        )
    )
    return AfiBoundarySnapshot(
        scope_ref=scope_ref,
        account_ref=account_ref,
        strategy_refs=strategy_values,
        paper_account_ids=account_values,
        paper_instance_ids=instance_values,
        operation_approval=_participant_facts(
            "afi_operations",
            source_ref,
            configuration_sha256,
            operation_rows,
            identity_links,
            (
                ServiceOrderOperation,
                ApprovedTargetHttpOperation,
                StrategyTargetApproval,
                StrategyTargetApprovalEvent,
            ),
            session,
        ),
        paper_ledger=_participant_facts(
            "afi_paper",
            source_ref,
            configuration_sha256,
            paper_rows,
            identity_links,
            (
                Account,
                Position,
                Order,
                PaperTrade,
                PaperEquitySnapshot,
                LegacyPaperImportReceipt,
            ),
            session,
        ),
        identity_links=identity_links,
        amounts=amounts,
        positions=position_amounts,
        unresolved_ids=unresolved_ids,
        reservation_ids=reservation_ids,
        _configuration_sha256=configuration_sha256,
    )


def enumerate_paper_snapshot_writers(
    session: Session,
    *,
    account_refs_by_paper_account: Mapping[str, str],
    configuration_sha256: str,
) -> tuple[AfiConfiguredSnapshotWriter, ...]:
    """Derive every restorable AFI snapshot consumer from persisted ownership.

    The selection predicate matches :meth:`PaperRuntimeSnapshotScheduler.start_existing`.
    Each selected instance must have bounded historical snapshot rows whose
    workspace, unit, user, and non-null paper-account FK agree with that
    configured runtime. The referenced Account row must confirm the same
    owner. Missing history, mixed/unbound FKs, owner drift, extra/missing
    account mappings, and oversized scans fail closed before a cutover can
    treat this producer as stopped.

    ``account_refs_by_paper_account`` is an explicit migration crosswalk. It
    labels the verified AFI account FK with the destination-side account_ref;
    it is not itself evidence that the mapping is authorized or a runtime
    grant. The caller must preserve and verify that crosswalk separately.
    """

    if (
        not isinstance(session, Session)
        or not session.is_active
        or session.new
        or session.dirty
        or session.deleted
        or type(account_refs_by_paper_account) is not dict
    ):
        raise AfiMigrationBoundaryError(CODE_BOUNDARY_READ_FAILED)
    _require_sha256(configuration_sha256)
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

    budget = _InventoryReadBudget()
    try:
        active_workspace_scope = (
            Workspace.workspace_type == "trading",
            StrategyUnit.trading_mode == "paper",
            StrategyUnit.run_status == "running",
            StrategyUnit.lock_running.is_(False),
            StrategyUnit.trading_instance_id.is_not(None),
        )
        active_unit_ids = (
            select(StrategyUnit.id)
            .join(Workspace, StrategyUnit.workspace_id == Workspace.id)
            .where(*active_workspace_scope)
        )
        active_workspace_ids = select(StrategyUnit.workspace_id).where(
            StrategyUnit.id.in_(active_unit_ids)
        )
        _preflight_query_budget(
            session,
            Workspace,
            select(Workspace).where(Workspace.id.in_(active_workspace_ids)),
            budget,
        )
        _preflight_query_budget(
            session,
            StrategyUnit,
            select(StrategyUnit).where(
                StrategyUnit.id.in_(active_unit_ids),
                StrategyUnit.workspace_id.in_(
                    select(Workspace.id).where(Workspace.workspace_type == "trading")
                ),
            ),
            budget,
        )
        configured_rows = list(
            session.execute(
                select(
                    Workspace.id.label("workspace_id"),
                    Workspace.user_id.label("user_id"),
                    StrategyUnit.id.label("unit_id"),
                    StrategyUnit.workspace_id.label("unit_workspace_id"),
                    StrategyUnit.trading_instance_id.label("instance_id"),
                )
                .join(StrategyUnit, StrategyUnit.workspace_id == Workspace.id)
                .where(*active_workspace_scope)
                .order_by(Workspace.id, StrategyUnit.id)
                .limit(_MAX_BOUNDARY_ROWS + 1)
            ).all()
        )
        if len(configured_rows) > _MAX_BOUNDARY_ROWS:
            raise AfiMigrationBoundaryError(CODE_BOUNDARY_READ_FAILED)
        if not configured_rows:
            if account_refs_by_paper_account:
                raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)
            return ()

        workspace_ids = tuple(sorted({row.workspace_id for row in configured_rows}))
        unit_ids = tuple(sorted({row.unit_id for row in configured_rows}))
        workspace_rows = _query_rows(
            session,
            Workspace,
            select(Workspace).where(Workspace.id.in_(workspace_ids)),
            budget,
        )
        unit_rows = _query_rows(
            session,
            StrategyUnit,
            select(StrategyUnit).where(StrategyUnit.id.in_(unit_ids)),
            budget,
        )
        workspaces = {row["id"]: row for row in workspace_rows}
        units = {row["id"]: row for row in unit_rows}
        if set(workspaces) != set(workspace_ids) or set(units) != set(unit_ids):
            raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)

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
                type(workspace_id) is not str
                or not workspace_id
                or type(user_id) is not str
                or not user_id
                or type(unit_id) is not str
                or not unit_id
                or type(instance_id) is not str
                or not instance_id
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
                    .limit(_MAX_BOUNDARY_ROWS + 1)
                ).all()
            )
            if not rows or len(rows) > _MAX_BOUNDARY_ROWS:
                raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)
            accounts_for_instance: set[str] = set()
            for row in rows:
                identity = tuple(row)
                encoded = _canonical_json(identity)
                snapshot_bytes += len(encoded)
                snapshot_rows_seen += 1
                if (
                    snapshot_rows_seen > _MAX_BOUNDARY_ROWS
                    or snapshot_bytes > _MAX_BOUNDARY_BYTES
                ):
                    raise AfiMigrationBoundaryError(CODE_BOUNDARY_READ_FAILED)
                (
                    snapshot_id,
                    snapshot_user_id,
                    snapshot_workspace_id,
                    snapshot_unit_id,
                    snapshot_instance_id,
                    paper_account_id,
                ) = identity
                if (
                    type(snapshot_id) is not str
                    or not snapshot_id
                    or (snapshot_user_id, snapshot_workspace_id, snapshot_unit_id, snapshot_instance_id)
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

        if set(account_refs_by_paper_account) != all_account_ids:
            raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)
        accounts = _query_rows(
            session,
            Account,
            select(Account).where(Account.id.in_(tuple(sorted(all_account_ids)))),
            budget,
        )
        account_by_id = {row["id"]: row for row in accounts}
        if set(account_by_id) != all_account_ids:
            raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)

        consumers = []
        operations = {"model": "PaperEquitySnapshot", "operation": "scheduled_snapshot"}
        operations_sha256 = hashlib.sha256(_canonical_json(operations)).hexdigest()
        for item in selected:
            account_id = item["paper_account_id"]
            if account_by_id[account_id]["user_id"] != item["user_id"]:
                raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)
            account_ref = account_refs_by_paper_account[account_id]
            workspace_row = workspaces[item["workspace_id"]]
            unit_row = units[item["unit_id"]]
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
                "scheduler": "app.services.paper_runtime_scheduler.PaperRuntimeSnapshotScheduler.start_existing",
                "workspace": workspace_row,
                "strategy_unit": unit_row,
                "verified_account_fk": account_id,
                "account_ref_crosswalk": account_ref,
            }
            configuration_digest = hashlib.sha256(
                _canonical_json(configuration_document)
            ).hexdigest()
            scope_digest = hashlib.sha256(
                _canonical_json(scope_document)
            ).hexdigest()
            consumer_id = "afi-snapshot-writer-v1:" + configuration_digest
            consumers.append(
                AfiConfiguredSnapshotWriter(
                    consumer_id=consumer_id,
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
    except AfiMigrationBoundaryError:
        raise
    except Exception:
        raise AfiMigrationBoundaryError(CODE_BOUNDARY_READ_FAILED) from None


async def stop_paper_snapshot_writers(
    scheduler: PaperRuntimeSnapshotScheduler,
    *,
    timeout_seconds: float = _SCHEDULER_STOP_TIMEOUT_SECONDS,
) -> PaperWriterStopReceipt:
    """Stop and verify all real AFI paper snapshot tasks before inventory."""

    if type(scheduler) is not PaperRuntimeSnapshotScheduler:
        raise AfiMigrationBoundaryError(CODE_WRITER_STILL_ACTIVE)
    if type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds):
        raise AfiMigrationBoundaryError(CODE_WRITER_STILL_ACTIVE)
    if timeout_seconds <= 0:
        raise AfiMigrationBoundaryError(CODE_WRITER_STILL_ACTIVE)
    task_map = getattr(scheduler, "_tasks", None)
    if type(task_map) is not dict:
        raise AfiMigrationBoundaryError(CODE_WRITER_STILL_ACTIVE)
    tasks_before = tuple(task_map.values())
    if any(not isinstance(task, asyncio.Task) for task in tasks_before):
        raise AfiMigrationBoundaryError(CODE_WRITER_STILL_ACTIVE)
    task_names = tuple(sorted(task.get_name() for task in tasks_before))
    try:
        await asyncio.wait_for(scheduler.shutdown(), timeout=float(timeout_seconds))
    except Exception:
        raise AfiMigrationBoundaryError(CODE_WRITER_STILL_ACTIVE) from None
    after_map = getattr(scheduler, "_tasks", None)
    if type(after_map) is not dict or after_map:
        raise AfiMigrationBoundaryError(CODE_WRITER_STILL_ACTIVE)
    if any(not task.done() for task in tasks_before):
        raise AfiMigrationBoundaryError(CODE_WRITER_STILL_ACTIVE)
    return PaperWriterStopReceipt(
        scheduler_type=f"{type(scheduler).__module__}.{type(scheduler).__qualname__}",
        tasks_before=len(tasks_before),
        stopped_task_names=task_names,
        tasks_after=0,
    )


def assert_afi_state_conserved(
    before: AfiBoundarySnapshot,
    after: AfiBoundarySnapshot,
) -> None:
    """Require in-place AFI identity and money/position projections to match."""

    if type(before) is not AfiBoundarySnapshot or type(after) is not AfiBoundarySnapshot:
        raise AfiMigrationBoundaryError(CODE_BOUNDARY_NOT_CONSERVED)
    if (
        before.scope_ref != after.scope_ref
        or before.account_ref != after.account_ref
        or before.strategy_refs != after.strategy_refs
        or before.paper_account_ids != after.paper_account_ids
        or before.paper_instance_ids != after.paper_instance_ids
        or before.operation_approval != after.operation_approval
        or before.paper_ledger != after.paper_ledger
        or before.identity_links != after.identity_links
        or before.amounts != after.amounts
        or before.positions != after.positions
        or before.unresolved_ids != after.unresolved_ids
        or before.reservation_ids != after.reservation_ids
    ):
        raise AfiMigrationBoundaryError(CODE_BOUNDARY_NOT_CONSERVED)


def _query_rows(
    session: Session,
    model: Any,
    statement: Any,
    budget: _InventoryReadBudget,
) -> tuple[dict[str, Any], ...]:
    _preflight_query_budget(session, model, statement, budget)
    result = session.execute(statement)
    columns = tuple(model.__table__.columns)
    properties_by_column: dict[str, str] = {}
    for property_ in sa_inspect(model).column_attrs:
        if len(property_.columns) != 1:
            raise AfiMigrationBoundaryError(CODE_BOUNDARY_READ_FAILED)
        column = property_.columns[0]
        if column.table is not model.__table__ or column.name in properties_by_column:
            raise AfiMigrationBoundaryError(CODE_BOUNDARY_READ_FAILED)
        properties_by_column[column.name] = property_.key
    if set(properties_by_column) != {column.name for column in columns}:
        raise AfiMigrationBoundaryError(CODE_BOUNDARY_READ_FAILED)
    rows = []
    for row in result.scalars():
        values = {
            properties_by_column[column.name]: _normal_value(
                getattr(row, properties_by_column[column.name])
            )
            for column in columns
        }
        encoded = _canonical_json(values)
        budget.rows += 1
        budget.bytes += len(encoded)
        if budget.rows > _MAX_BOUNDARY_ROWS or budget.bytes > _MAX_BOUNDARY_BYTES:
            raise AfiMigrationBoundaryError(CODE_BOUNDARY_READ_FAILED)
        rows.append(values)
    rows.sort(key=_canonical_json)
    return tuple(rows)


def _preflight_query_budget(
    session: Session,
    model: Any,
    statement: Any,
    budget: _InventoryReadBudget,
) -> None:
    """Reject oversized selected data before ORM materializes entity values."""

    where_clause = statement.whereclause
    count_query = select(func.count()).select_from(model)
    if where_clause is not None:
        count_query = count_query.where(where_clause)
    row_count = session.scalar(count_query)
    if type(row_count) is not int or row_count < 0 or budget.rows + row_count > _MAX_BOUNDARY_ROWS:
        raise AfiMigrationBoundaryError(CODE_BOUNDARY_READ_FAILED)

    columns = tuple(model.__table__.columns)
    byte_lengths = []
    for column in columns:
        if isinstance(column.type, LargeBinary):
            byte_lengths.append(
                func.coalesce(func.sum(func.length(column)), 0)
            )
        elif isinstance(column.type, (String, Text, JSON)):
            # SQL length counts Unicode code points on supported backends;
            # six bytes per code point bounds UTF-8 plus JSON escaping.
            byte_lengths.append(
                6 * func.coalesce(func.sum(func.length(cast(column, String))), 0)
            )
    if byte_lengths:
        size_query = select(*byte_lengths).select_from(model)
        if where_clause is not None:
            size_query = size_query.where(where_clause)
        lengths = session.execute(size_query).one()
        estimated_value_bytes = sum(int(value) for value in lengths)
    else:
        estimated_value_bytes = 0
    row_overhead = 64 + sum(len(column.name.encode("utf-8")) + 32 for column in columns)
    estimated_bytes = estimated_value_bytes + row_count * row_overhead
    if budget.bytes + estimated_bytes > _MAX_BOUNDARY_BYTES:
        raise AfiMigrationBoundaryError(CODE_BOUNDARY_READ_FAILED)


def _http_operation_matches_approval(
    operation: dict[str, Any], approval: dict[str, Any]
) -> bool:
    return all(
        operation[operation_field] == approval[approval_field]
        for operation_field, approval_field in (
            ("approval_version", "approval_version"),
            ("target_sha256", "target_sha256"),
            ("request_sha256", "operation_request_sha256"),
            ("intent_id", "intent_id"),
            ("operation_key_sha256", "operation_key_sha256"),
            ("scope_ref", "scope_ref"),
            ("account_ref", "account_ref"),
            ("strategy_ref", "strategy_ref"),
        )
    )


def _validate_approval_event_chains(
    approvals: tuple[dict[str, Any], ...],
    events: tuple[dict[str, Any], ...],
) -> None:
    events_by_ref: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        if (
            type(event.get("record_version")) is not int
            or event["record_version"] < 1
            or type(event.get("approval_version")) is not int
        ):
            raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)
        events_by_ref.setdefault(event["approval_ref"], []).append(event)
    for approval in approvals:
        if type(approval.get("approval_version")) is not int:
            raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)
        approval_events = sorted(
            events_by_ref.get(approval["approval_ref"], ()),
            key=lambda row: row["record_version"],
        )
        record_version = approval["record_version"]
        if (
            type(record_version) is not int
            or record_version < 1
            or not approval_events
            or [row["record_version"] for row in approval_events]
            != list(range(1, record_version + 1))
            or any(
                row["approval_version"] != approval["approval_version"]
                for row in approval_events
            )
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
        reserved_events = [
            row for row in approval_events if row["event_type"] == "OPERATION_RESERVED"
        ]
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
        if (
            len(reserved_events) != int(has_reserved_operation)
            or any(
                row["intent_id"] != approval["intent_id"]
                or row["operation_key_sha256"] != approval["operation_key_sha256"]
                or row["occurred_at_ns"] != approval["operation_reserved_at_ns"]
                for row in reserved_events
            )
        ):
            raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)
        expected_prefix = ("APPROVED",) + (
            ("OPERATION_RESERVED",) if has_reserved_operation else ()
        )
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
        if state == "CONSUMED":
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


def _validate_identity_fields(
    operations: tuple[dict[str, Any], ...],
    http_operations: tuple[dict[str, Any], ...],
    approvals: tuple[dict[str, Any], ...],
    events: tuple[dict[str, Any], ...],
    accounts: tuple[dict[str, Any], ...],
    positions: tuple[dict[str, Any], ...],
    orders: tuple[dict[str, Any], ...],
    trades: tuple[dict[str, Any], ...],
    snapshots: tuple[dict[str, Any], ...],
    import_receipts: tuple[dict[str, Any], ...],
) -> None:
    fields = (
        (operations, ("operation_key_sha256", "intent_id", "scope_ref", "account_ref")),
        (
            http_operations,
            (
                "operation_key_sha256",
                "approval_ref",
                "intent_id",
                "scope_ref",
                "account_ref",
                "strategy_ref",
            ),
        ),
        (approvals, ("approval_ref", "scope_ref", "account_ref", "strategy_ref", "target_ref")),
        (events, ("id", "approval_ref", "event_type")),
        (accounts, ("id", "user_id")),
        (positions, ("id", "account_id", "symbol")),
        (orders, ("id", "account_id", "symbol", "status")),
        (trades, ("id", "account_id", "symbol")),
        (snapshots, ("id", "user_id", "instance_id")),
        (
            import_receipts,
            (
                "id",
                "legacy_account_id",
                "owner_subject",
                "state",
                "target_scope_key",
                "target_account_key",
                "cash_currency",
            ),
        ),
    )
    if any(
        type(row.get(field)) is not str or not row[field]
        for rows, names in fields
        for row in rows
        for field in names
    ):
        raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)
    hash_fields = (
        (operations, ("operation_key_sha256", "request_sha256")),
        (http_operations, ("operation_key_sha256", "request_sha256", "target_sha256")),
        (approvals, ("target_sha256", "policy_sha256")),
        (events, ("target_sha256",)),
        (
            import_receipts,
            (
                "source_inventory_sha256",
                "target_import_sha256",
                "target_domain_sha256",
                "binding_sha256",
                "preserved_context_sha256",
            ),
        ),
    )
    if any(
        not _valid_sha256(row[field])
        for rows, names in hash_fields
        for row in rows
        for field in names
    ):
        raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)
    for approval in approvals:
        if any(
            value is not None and not _valid_sha256(value)
            for value in (
                approval["membership_sha256"],
                approval["operation_key_sha256"],
                approval["operation_request_sha256"],
                approval["consumed_intent_sha256"],
            )
        ):
            raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)
    for event in events:
        if any(
            value is not None and not _valid_sha256(value)
            for value in (
                event["operation_key_sha256"],
                event["intent_sha256"],
            )
        ):
            raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)
    if any(
        type(row.get("approval_version")) is not int or row["approval_version"] < 1
        for rows in (http_operations, approvals, events)
        for row in rows
    ):
        raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)
    if any(
        type(row.get("receipt_version")) is not int
        or row["receipt_version"] != 1
        or type(row.get("generation")) is not int
        or row["generation"] < 1
        or any(
            type(row.get(field)) is not int or row[field] < 0
            for field in (
                "source_order_count",
                "source_position_count",
                "source_trade_count",
            )
        )
        for row in import_receipts
    ):
        raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)
    if any(
        type(row.get("manual_book_ref")) is not str or not row["manual_book_ref"]
        for row in operations
    ):
        raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)
    order_ids = {row["id"] for row in orders}
    if any(
        row["order_id"] is not None and row["order_id"] not in order_ids
        for row in trades
    ):
        raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)


def _validate_import_receipts(
    receipts: tuple[dict[str, Any], ...],
    accounts: tuple[dict[str, Any], ...],
    account_values: tuple[str, ...],
) -> None:
    """Validate AFI12 source-side handoff receipts before inventorying them."""

    users_by_account = {row["id"]: row["user_id"] for row in accounts}
    generations: set[tuple[str, int]] = set()
    active_accounts: set[str] = set()
    for row in receipts:
        account_id = row.get("legacy_account_id")
        state = row.get("state")
        string_fields = (
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
        if any(type(row.get(field)) is not str or not row[field] for field in string_fields):
            raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)
        if (
            account_id not in account_values
            or row.get("owner_subject") != users_by_account.get(account_id)
            or type(row.get("receipt_version")) is not int
            or row["receipt_version"] != 1
            or type(row.get("generation")) is not int
            or row["generation"] < 1
            or any(
                type(row.get(field)) is not int or row[field] < 0
                for field in (
                    "source_order_count",
                    "source_position_count",
                    "source_trade_count",
                )
            )
            or any(
                not _valid_sha256(row[field])
                for field in (
                    "source_inventory_sha256",
                    "target_import_sha256",
                    "target_domain_sha256",
                    "binding_sha256",
                    "preserved_context_sha256",
                )
            )
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
                _canonical_json(source_document) != source_bytes
                or hashlib.sha256(source_bytes).hexdigest() != row["source_inventory_sha256"]
                or _canonical_json(context_document) != context_bytes
                or hashlib.sha256(context_bytes).hexdigest()
                != row["preserved_context_sha256"]
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
        for field in (
            "opening_cash",
            "cumulative_fees",
            "unallocated_equity_residual",
        ):
            value = row.get(field)
            if type(value) is not str:
                raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)
            try:
                decimal_value = Decimal(value)
            except (InvalidOperation, ValueError):
                raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE) from None
            if not decimal_value.is_finite():
                raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)


def _participant_facts(
    participant_id: str,
    source_ref: str,
    configuration_sha256: str,
    named_rows: tuple[tuple[str, tuple[dict[str, Any], ...]], ...],
    links: tuple[tuple[str, str, str, str], ...],
    models: tuple[type, ...],
    session: Session,
) -> AfiParticipantFacts:
    schema = _inspected_schema_rows(session, models)
    schema_digest = hashlib.sha256(_canonical_json(schema)).hexdigest()
    payload = _canonical_json(
        {
            "schema": 1,
            "model_schema_sha256": schema_digest,
            "participant_id": participant_id,
            "configuration_sha256": configuration_sha256,
            "tables": [
                (table, [_canonical_value(row) for row in rows]) for table, rows in named_rows
            ],
        }
    )
    participant_links = (
        tuple(link for link in links if not link[0].startswith("paper_"))
        if participant_id == "afi_operations"
        else tuple(link for link in links if link[0].startswith("paper_"))
    )
    identity_digest = hashlib.sha256(_canonical_json(participant_links)).hexdigest()
    return AfiParticipantFacts(
        participant_id=participant_id,
        source_ref=source_ref,
        state_sha256=hashlib.sha256(payload).hexdigest(),
        identity_sha256=identity_digest,
        schema_sha256=schema_digest,
        row_count=sum(len(rows) for _, rows in named_rows),
    )


def _inspected_schema_rows(session: Session, models: tuple[type, ...]) -> tuple[Any, ...]:
    try:
        inspector = sa_inspect(session.get_bind())
        rows = []
        for model in models:
            table = model.__table__
            schema = table.schema
            rows.append(
                (
                    table.name,
                    tuple(
                        _schema_value(item)
                        for item in inspector.get_columns(table.name, schema=schema)
                    ),
                    _schema_value(inspector.get_pk_constraint(table.name, schema=schema)),
                    tuple(
                        sorted(
                            (_schema_value(item) for item in inspector.get_unique_constraints(
                                table.name, schema=schema
                            )),
                            key=_canonical_json,
                        )
                    ),
                    tuple(
                        sorted(
                            (_schema_value(item) for item in inspector.get_indexes(
                                table.name, schema=schema
                            )),
                            key=_canonical_json,
                        )
                    ),
                    tuple(
                        sorted(
                            (_schema_value(item) for item in inspector.get_foreign_keys(
                                table.name, schema=schema
                            )),
                            key=_canonical_json,
                        )
                    ),
                    tuple(
                        sorted(
                            (_schema_value(item) for item in inspector.get_check_constraints(
                                table.name, schema=schema
                            )),
                            key=_canonical_json,
                        )
                    ),
                )
            )
        return tuple(rows)
    except Exception:
        raise AfiMigrationBoundaryError(CODE_BOUNDARY_READ_FAILED) from None


def _schema_value(value: Any) -> Any:
    if value is None or type(value) in (str, int, bool):
        return value
    if isinstance(value, (tuple, list)):
        return [_schema_value(item) for item in value]
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            raise AfiMigrationBoundaryError(CODE_BOUNDARY_READ_FAILED)
        return {key: _schema_value(item) for key, item in value.items()}
    return str(value)


def _identity_links(
    account_ref: str,
    paper_account_id: str,
    operations: tuple[dict[str, Any], ...],
    http_operations: tuple[dict[str, Any], ...],
    approvals: tuple[dict[str, Any], ...],
    events: tuple[dict[str, Any], ...],
    accounts: tuple[dict[str, Any], ...],
    positions: tuple[dict[str, Any], ...],
    orders: tuple[dict[str, Any], ...],
    trades: tuple[dict[str, Any], ...],
    snapshots: tuple[dict[str, Any], ...],
    import_receipts: tuple[dict[str, Any], ...],
) -> tuple[tuple[str, str, str, str], ...]:
    links: list[tuple[str, str, str, str]] = [
        ("paper_account_ref", account_ref, "paper_account", paper_account_id)
    ]
    for row in operations:
        links.append(
            (
                "afi_operations.manual_key",
                row["operation_key_sha256"],
                "execution.intent_id",
                row["intent_id"],
            )
        )
    for row in http_operations:
        links.append(
            (
                "afi_operations.http_key",
                row["operation_key_sha256"],
                "afi_approval_ref",
                row["approval_ref"],
            )
        )
        links.append(
            (
                "afi_approval_ref",
                row["approval_ref"],
                "execution.intent_id",
                row["intent_id"],
            )
        )
    for row in approvals:
        links.append(
            (
                "afi_approval_ref",
                row["approval_ref"],
                "execution.intent_id",
                row["intent_id"] or "UNRESERVED",
            )
        )
        links.append(
            (
                "afi_approval_ref",
                row["approval_ref"],
                "afi_target_ref",
                row["target_ref"],
            )
        )
    for row in events:
        links.append(
            (
                "afi_approval_event",
                row["id"],
                "afi_approval_ref",
                row["approval_ref"],
            )
        )
    for row in accounts:
        links.append(("paper_account", row["id"], "paper_user", row["user_id"]))
    for row in positions:
        links.append(("paper_position", row["id"], "paper_account", row["account_id"]))
    for row in orders:
        links.append(("paper_order", row["id"], "paper_account", row["account_id"]))
    for row in trades:
        if row["order_id"] is not None:
            links.append(("paper_trade", row["id"], "paper_order", row["order_id"]))
        links.append(("paper_trade", row["id"], "paper_account", row["account_id"]))
    for row in snapshots:
        links.append(
            (
                "paper_equity_snapshot",
                row["id"],
                "paper_account",
                row["paper_account_id"] or "UNBOUND",
            )
        )
        metadata = row["metadata_json"]
        if type(metadata) is dict and metadata.get("run_ref") is not None:
            run_ref = metadata["run_ref"]
            if type(run_ref) is not str or not run_ref:
                raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)
            links.append(
                ("paper_equity_snapshot", row["id"], "paper_run_ref", run_ref)
            )
        links.append(
            (
                "paper_equity_snapshot",
                row["id"],
                "paper_instance",
                row["instance_id"],
            )
        )
    for row in import_receipts:
        links.extend(
            (
                (
                    "paper_import_receipt",
                    row["id"],
                    "paper_account",
                    row["legacy_account_id"],
                ),
                (
                    "paper_import_receipt",
                    row["id"],
                    "paper_import_source_sha256",
                    row["source_inventory_sha256"],
                ),
                (
                    "paper_import_receipt",
                    row["id"],
                    "paper_import_target_scope",
                    row["target_scope_key"],
                ),
                (
                    "paper_import_receipt",
                    row["id"],
                    "paper_import_target_account",
                    row["target_account_key"],
                ),
                (
                    "paper_import_receipt",
                    row["id"],
                    "paper_import_fence",
                    row["active_fence_key"] or "NO_ACTIVE_FENCE",
                ),
            )
        )
    return tuple(sorted(links))


def _financial_amounts(
    accounts: tuple[dict[str, Any], ...],
    positions: tuple[dict[str, Any], ...],
    orders: tuple[dict[str, Any], ...],
    trades: tuple[dict[str, Any], ...],
    snapshots: tuple[dict[str, Any], ...],
    import_receipts: tuple[dict[str, Any], ...],
) -> tuple[tuple[str, str], ...]:
    values: list[tuple[str, Decimal]] = []
    for row in accounts:
        account_id = row["id"]
        for key in ("initial_cash", "current_cash", "total_equity", "profit_loss"):
            values.append((f"account:{account_id}:{key}", _decimal(row[key])))
    for row in positions:
        for key in ("market_value", "margin_value", "unrealized_pnl"):
            values.append((f"position:{row['id']}:{key}", _decimal(row[key])))
    for row in orders:
        for key in ("filled_size", "avg_fill_price", "commission", "slippage"):
            values.append((f"order:{row['id']}:{key}", _decimal(row[key])))
    for row in trades:
        for key in ("size", "price", "commission", "slippage", "pnl"):
            values.append((f"trade:{row['id']}:{key}", _decimal(row[key])))
    for row in snapshots:
        for key in (
            "total_equity",
            "cash",
            "position_value",
            "unrealized_pnl",
            "realized_pnl",
        ):
            values.append((f"equity_snapshot:{row['id']}:{key}", _decimal(row[key])))
    for row in import_receipts:
        for key in ("opening_cash", "cumulative_fees", "unallocated_equity_residual"):
            values.append(
                (f"legacy_import_receipt:{row['id']}:{key}", _decimal(row[key]))
            )
    return tuple(sorted((key, _decimal_text(value)) for key, value in values))


def _position_amounts(
    positions: tuple[dict[str, Any], ...],
) -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted(
            (f"{row['account_id']}:{row['symbol']}:{row['id']}", _decimal_text(_decimal(row["size"])))
            for row in positions
        )
    )


def _normal_scalar_value(value: Any) -> Any:
    if value is None or type(value) in (str, int, bool):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise AfiMigrationBoundaryError(CODE_BOUNDARY_READ_FAILED)
        return {"float_hex": value.hex()}
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise AfiMigrationBoundaryError(CODE_BOUNDARY_READ_FAILED)
        return {"decimal": _decimal_text(value)}
    if isinstance(value, (datetime, date)):
        return {"datetime": value.isoformat()}
    raise AfiMigrationBoundaryError(CODE_BOUNDARY_READ_FAILED)


def _normal_value(value: Any) -> Any:
    if type(value) in (dict, list, tuple):
        return _normal_json_value(value)
    return _normal_scalar_value(value)


def _normal_json_value(value: Any) -> Any:
    if type(value) is list or type(value) is tuple:
        return [_normal_json_value(item) for item in value]
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            raise AfiMigrationBoundaryError(CODE_BOUNDARY_READ_FAILED)
        return {key: _normal_json_value(item) for key, item in value.items()}
    return _normal_scalar_value(value)


def _canonical_value(value: Any) -> Any:
    return value


def _canonical_json(value: Any) -> bytes:
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


def _decimal(value: Any) -> Decimal:
    try:
        if type(value) is dict:
            if set(value) == {"float_hex"} and type(value["float_hex"]) is str:
                source_float = float.fromhex(value["float_hex"])
                if (
                    not math.isfinite(source_float)
                    or source_float.hex() != value["float_hex"]
                ):
                    raise AfiMigrationBoundaryError(CODE_BOUNDARY_READ_FAILED)
                number = Decimal(str(source_float))
            elif set(value) == {"decimal"} and type(value["decimal"]) is str:
                decimal_text = value["decimal"]
                number = Decimal(decimal_text)
                if not number.is_finite() or _decimal_text(number) != decimal_text:
                    raise AfiMigrationBoundaryError(CODE_BOUNDARY_READ_FAILED)
            else:
                raise AfiMigrationBoundaryError(CODE_BOUNDARY_READ_FAILED)
        elif isinstance(value, Decimal):
            number = value
        elif type(value) is float:
            if not math.isfinite(value):
                raise AfiMigrationBoundaryError(CODE_BOUNDARY_READ_FAILED)
            number = Decimal(str(value))
        elif type(value) in (str, int):
            number = Decimal(value)
        else:
            raise AfiMigrationBoundaryError(CODE_BOUNDARY_READ_FAILED)
    except (InvalidOperation, ValueError, TypeError):
        raise AfiMigrationBoundaryError(CODE_BOUNDARY_READ_FAILED) from None
    if not number.is_finite():
        raise AfiMigrationBoundaryError(CODE_BOUNDARY_READ_FAILED)
    _decimal_text(number)
    return number


def _decimal_text(value: Decimal) -> str:
    sign, digits_tuple, exponent = value.as_tuple()
    if not any(digit != 0 for digit in digits_tuple):
        return "0"
    digits = "".join(str(digit) for digit in digits_tuple)
    digits = digits.rstrip("0")
    exponent += len(digits_tuple) - len(digits)
    if len(digits) > 256 or abs(exponent) > 256:
        raise AfiMigrationBoundaryError(CODE_BOUNDARY_READ_FAILED)
    if exponent >= 0:
        body = digits + ("0" * exponent)
    else:
        point = len(digits) + exponent
        body = (
            digits[:point] + "." + digits[point:]
            if point > 0
            else "0." + ("0" * -point) + digits
        )
    return ("-" if sign else "") + body


def _text_set(values: Iterable[str]) -> tuple[str, ...]:
    if type(values) not in (tuple, list) or len(values) > _MAX_BOUNDARY_ROWS:
        raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE) from None
    if any(type(value) is not str or not value for value in values) or len(set(values)) != len(values):
        raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)
    result = tuple(sorted(values))
    return result


def _require_text(value: Any) -> None:
    if type(value) is not str or not value:
        raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)


def _require_sha256(value: Any) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise AfiMigrationBoundaryError(CODE_INVALID_BOUNDARY_SCOPE)


def _valid_sha256(value: Any) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )
