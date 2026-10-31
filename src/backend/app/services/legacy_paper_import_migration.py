"""Controlled, source-fenced import of non-empty legacy paper accounts.

The legacy rows remain the historical source of truth.  The Execution store
receives only an ``imported_legacy`` baseline and immutable provenance; this
module never creates provider receipts or synthetic order events.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError

from app.db import database
from app.models.alerts import Alert, AlertNotification, AlertRule
from app.models.legacy_paper_cutover import LegacyPaperCutoverReceipt, LegacyPaperWriterLease
from app.models.legacy_paper_import import LegacyPaperImportReceipt, LegacyPaperImportReceiptView
from app.models.paper_runtime import (
    LiveHandoffReview,
    PaperEquitySnapshot,
    PaperReviewReport,
    RiskRule,
)
from app.models.paper_trading import Account, Order, PaperTrade, Position
from app.models.strategy_approval_authority import (
    StrategyApprovalAuthorityEpoch,
    StrategyOrderApprovalPolicyHead,
    StrategyOrderApprovalPolicyVersion,
)
from app.models.strategy_target_approval import StrategyTargetApproval, StrategyTargetApprovalEvent
from app.models.user import User
from app.models.workspace import StrategyUnit, Workspace
from app.services.legacy_paper_migration import (
    MAX_INVENTORY_ROWS_PER_TABLE,
    LegacyPaperInventory,
    LegacyPaperInventoryError,
    _binding_value,
    _decimal,
    _identifier,
    _model_row,
    _paper_binding_payload,
    inspect_stable_legacy_paper_account,
    paper_binding_fingerprint,
    prepare_empty_account_cutover,
)

_MAX_PRESERVED_CONTEXT_BYTES = 8 * 1024 * 1024
_MAX_CONTEXT_ROWS_PER_TABLE = 20_000


async def _validate_runtime_instance_account_bindings(
    session: Any, *, owner_subject: str
) -> None:
    """Require persisted, unambiguous account links for owned runtimes.

    A runtime's JSON configuration is not an identity binding.  The only
    source relation available here is a non-null paper_account_id recorded on
    every snapshot for the canonical runtime instance.
    """
    unit_result = await session.execute(
        select(Workspace.id, StrategyUnit.id, StrategyUnit.trading_instance_id)
        .join(StrategyUnit, StrategyUnit.workspace_id == Workspace.id)
        .where(
            Workspace.user_id == owner_subject,
            StrategyUnit.trading_instance_id.is_not(None),
        )
        .order_by(Workspace.id.asc(), StrategyUnit.id.asc())
        .limit(_MAX_CONTEXT_ROWS_PER_TABLE + 1)
    )
    unit_rows = list(unit_result.all())
    if len(unit_rows) > _MAX_CONTEXT_ROWS_PER_TABLE:
        raise LegacyPaperImportError("LEGACY_CONTEXT_LIMIT_EXCEEDED")
    runtime_units: dict[str, tuple[str, str]] = {}
    for workspace_id, unit_id, instance_id in unit_rows:
        if not all(type(value) is str and value for value in (workspace_id, unit_id, instance_id)):
            raise LegacyPaperImportError("LEGACY_RUNTIME_INSTANCE_RELATION_UNPROVEN")
        if instance_id in runtime_units:
            raise LegacyPaperImportError("LEGACY_RUNTIME_INSTANCE_RELATION_UNPROVEN")
        runtime_units[instance_id] = (workspace_id, unit_id)

    snapshot_result = await session.execute(
        select(
            PaperEquitySnapshot.id,
            PaperEquitySnapshot.workspace_id,
            PaperEquitySnapshot.unit_id,
            PaperEquitySnapshot.instance_id,
            PaperEquitySnapshot.paper_account_id,
        )
        .where(PaperEquitySnapshot.user_id == owner_subject)
        .order_by(PaperEquitySnapshot.id.asc())
        .limit(_MAX_CONTEXT_ROWS_PER_TABLE + 1)
    )
    snapshot_rows = list(snapshot_result.all())
    if len(snapshot_rows) > _MAX_CONTEXT_ROWS_PER_TABLE:
        raise LegacyPaperImportError("LEGACY_CONTEXT_LIMIT_EXCEEDED")

    accounts_by_instance: dict[str, set[str]] = {}
    for _, workspace_id, unit_id, instance_id, account_id in snapshot_rows:
        unit_identity = runtime_units.get(instance_id)
        if (
            unit_identity is None
            or unit_identity != (workspace_id, unit_id)
            or type(account_id) is not str
            or not account_id
        ):
            raise LegacyPaperImportError("LEGACY_RUNTIME_INSTANCE_RELATION_UNPROVEN")
        accounts_by_instance.setdefault(instance_id, set()).add(account_id)

    if any(len(account_ids) != 1 for account_ids in accounts_by_instance.values()):
        raise LegacyPaperImportError("LEGACY_RUNTIME_INSTANCE_RELATION_UNPROVEN")
    if any(instance_id not in accounts_by_instance for instance_id in runtime_units):
        raise LegacyPaperImportError("LEGACY_RUNTIME_INSTANCE_RELATION_UNPROVEN")

    account_ids = sorted(
        {next(iter(account_ids)) for account_ids in accounts_by_instance.values()}
    )
    if account_ids:
        account_result = await session.execute(
            select(Account.id)
            .join(
                PaperEquitySnapshot,
                PaperEquitySnapshot.paper_account_id == Account.id,
            )
            .where(
                PaperEquitySnapshot.user_id == owner_subject,
                Account.user_id == owner_subject,
            )
        )
        owned_accounts = {row[0] for row in account_result.all()}
        if owned_accounts != set(account_ids):
            raise LegacyPaperImportError("LEGACY_RUNTIME_INSTANCE_RELATION_UNPROVEN")

async def _read_runtime_instance_account_bindings(
    owner_subject: str,
) -> None:
    async with database.async_session_maker() as session:
        await _validate_runtime_instance_account_bindings(
            session, owner_subject=owner_subject
        )


class LegacyPaperImportError(RuntimeError):
    """Finite, non-sensitive failure at the legacy import boundary."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class LegacyPaperImportResult:
    receipt: LegacyPaperImportReceiptView
    legacy_ledger_retained_read_only: bool = True
    imported_rows_are_exchange_facts: bool = False
    old_rules_approvals_alerts_activated: bool = False


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _validate_source_pnl_projection(account: Mapping[str, Any]) -> None:
    initial_cash = _decimal(account.get("initial_cash"))
    total_equity = _decimal(account.get("total_equity"))
    profit_loss = _decimal(account.get("profit_loss"))
    profit_loss_pct = _decimal(account.get("profit_loss_pct"))
    if None in {initial_cash, total_equity, profit_loss, profit_loss_pct}:
        raise LegacyPaperImportError("LEGACY_PNL_NOT_RECONCILED")

    expected_profit_loss = total_equity - initial_cash
    pnl_tolerance = max(
        Decimal("1e-12"),
        max(abs(expected_profit_loss), abs(profit_loss)) * Decimal("1e-12"),
    )
    if abs(profit_loss - expected_profit_loss) > pnl_tolerance:
        raise LegacyPaperImportError("LEGACY_PNL_NOT_RECONCILED")

    if initial_cash == 0:
        expected_profit_loss_pct = Decimal(0)
    else:
        expected_profit_loss_pct = profit_loss / initial_cash * Decimal(100)
    pct_tolerance = max(
        Decimal("1e-10"),
        max(abs(expected_profit_loss_pct), abs(profit_loss_pct)) * Decimal("1e-12"),
    )
    if abs(profit_loss_pct - expected_profit_loss_pct) > pct_tolerance:
        raise LegacyPaperImportError("LEGACY_PNL_NOT_RECONCILED")


def _view(row: LegacyPaperImportReceipt) -> LegacyPaperImportReceiptView:
    return LegacyPaperImportReceiptView(
        receipt_id=row.id,
        legacy_account_id=row.legacy_account_id,
        generation=row.generation,
        state=row.state,
        owner_subject=row.owner_subject,
        source_inventory_sha256=row.source_inventory_sha256,
        target_import_sha256=row.target_import_sha256,
        target_domain_sha256=row.target_domain_sha256,
        binding_sha256=row.binding_sha256,
        target_scope_key=row.target_scope_key,
        target_account_key=row.target_account_key,
        cash_currency=row.cash_currency,
        opening_cash=row.opening_cash,
        cumulative_fees=row.cumulative_fees,
        unallocated_equity_residual=row.unallocated_equity_residual,
        source_order_count=row.source_order_count,
        source_position_count=row.source_position_count,
        source_trade_count=row.source_trade_count,
        preserved_context_sha256=row.preserved_context_sha256,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _next_timestamp(previous: datetime | None = None) -> datetime:
    now = datetime.now(timezone.utc)
    if previous is None:
        return now
    prior = previous.replace(tzinfo=timezone.utc) if previous.tzinfo is None else previous
    return max(now, prior + timedelta(microseconds=1))


def _require_server_binding(binding: Any, scope: Any, domain: Any) -> dict[str, Any]:
    try:
        from bt_api_execution import PAPER_ENVIRONMENT, PAPER_PROVIDER, PaperOwnerDomainV1
        from bt_api_execution.contracts import ExecutionScope
    except Exception:
        raise LegacyPaperImportError("EXECUTION_IMPORT_CONTRACT_UNAVAILABLE") from None

    if type(scope) is not ExecutionScope or type(domain) is not PaperOwnerDomainV1:
        raise LegacyPaperImportError("INVALID_PAPER_BINDING")
    try:
        payload = _paper_binding_payload(binding)
    except LegacyPaperInventoryError as error:
        raise LegacyPaperImportError(error.code) from None
    if (
        payload["mount"] != "application.orders"
        or scope.provider != PAPER_PROVIDER
        or scope.environment != PAPER_ENVIRONMENT
        or scope.account_ref != payload["account_ref"]
        or scope.strategy_id != payload["strategy_ref"]
        or domain.execution_domain_ref != payload["execution_domain_ref"]
        or domain.simulation_account_ref != payload["account_ref"]
        or domain.strategy_ref != payload["strategy_ref"]
        or domain.experiment_ref != payload["experiment_ref"]
        or domain.model_ref != payload["model_ref"]
        or domain.model_version != payload["model_version"]
        or domain.quote_source_ref != payload["quote_source_ref"]
        or domain.cash_currency != payload["cash_currency"]
        or domain.fingerprint != payload["paper_domain_sha256"]
        or format(domain.initial_cash, "f") != payload["initial_cash"]
        or format(domain.initial_fees, "f") != payload["initial_fees"]
        or format(domain.fee_rate, "f") != payload["fee_rate"]
        or format(domain.fee_quantum, "f") != payload["fee_quantum"]
        or domain.max_quote_age_ns != payload["max_quote_age_ns"]
        or payload["instrument_metadata_versions"]
        != {item.instrument: item.metadata_version for item in domain.instruments}
        or payload["opening_positions"]
        != [item.to_payload() for item in domain.opening_positions]
    ):
        raise LegacyPaperImportError("INVALID_PAPER_BINDING")
    return payload


async def _source_snapshot_in_session(
    session: Any, account: Account, *, owner_subject: str
) -> tuple[LegacyPaperInventory, dict[str, Any], str]:
    account_row = _model_row(account)
    if account.user_id != owner_subject:
        raise LegacyPaperImportError("LEGACY_OWNER_MISMATCH")
    table_rows: dict[str, list[dict[str, Any]]] = {}
    for name, model in (("orders", Order), ("positions", Position), ("trades", PaperTrade)):
        rows = list(
            (
                await session.execute(
                    select(model)
                    .where(model.account_id == account.id)
                    .order_by(model.id.asc())
                    .limit(MAX_INVENTORY_ROWS_PER_TABLE + 1)
                )
            )
            .scalars()
            .all()
        )
        if len(rows) > MAX_INVENTORY_ROWS_PER_TABLE:
            raise LegacyPaperImportError("LEGACY_INVENTORY_LIMIT_EXCEEDED")
        table_rows[name] = [_model_row(row) for row in rows]

    document = {
        "schema": "afi.legacy-paper-inventory.v1",
        "account": account_row,
        "orders": table_rows["orders"],
        "positions": table_rows["positions"],
        "trades": table_rows["trades"],
    }
    try:
        document_json = _canonical_json(document)
    except (TypeError, ValueError, UnicodeError):
        raise LegacyPaperImportError("LEGACY_INVENTORY_UNREADABLE") from None
    digest = _sha256_text(document_json)
    inventory = LegacyPaperInventory(
        account_id=account.id,
        owner_id=owner_subject,
        complete=True,
        digest=digest,
        account=account_row,
        order_count=len(table_rows["orders"]),
        position_count=len(table_rows["positions"]),
        trade_count=len(table_rows["trades"]),
        reasons=(),
    )
    return inventory, document, document_json


async def _bounded_rows(session: Any, model: Any, *predicates: Any) -> list[dict[str, Any]]:
    primary_key = tuple(model.__table__.primary_key.columns)
    statement = select(model).where(*predicates).order_by(*(column.asc() for column in primary_key))
    rows = list((await session.execute(statement.limit(_MAX_CONTEXT_ROWS_PER_TABLE + 1))).scalars())
    if len(rows) > _MAX_CONTEXT_ROWS_PER_TABLE:
        raise LegacyPaperImportError("LEGACY_CONTEXT_LIMIT_EXCEEDED")
    try:
        return [_model_row(row) for row in rows]
    except (LegacyPaperInventoryError, TypeError, ValueError):
        raise LegacyPaperImportError("LEGACY_CONTEXT_UNREADABLE") from None


async def _preserved_context(
    session: Any,
    *,
    owner_subject: str,
    binding_payload: Mapping[str, Any],
    document: Mapping[str, Any],
) -> tuple[dict[str, Any], str, str]:
    account_id = str(binding_payload["legacy_account_id"])
    order_ids = [row["id"] for row in document["orders"]]
    position_ids = [row["id"] for row in document["positions"]]
    alerts_predicates = [Alert.account_id == account_id]
    if order_ids:
        alerts_predicates.append(Alert.order_id.in_(order_ids))
    if position_ids:
        alerts_predicates.append(Alert.position_id.in_(position_ids))
    alerts = await _bounded_rows(session, Alert, or_(*alerts_predicates))
    alert_ids = [row["id"] for row in alerts]
    alert_rule_ids = sorted({row["rule_id"] for row in alerts if row.get("rule_id")})

    scoped_approvals = await _bounded_rows(
        session,
        StrategyTargetApproval,
        StrategyTargetApproval.owner_subject == owner_subject,
        StrategyTargetApproval.execution_domain_ref == binding_payload["execution_domain_ref"],
        StrategyTargetApproval.account_ref == binding_payload["account_ref"],
        StrategyTargetApproval.strategy_ref == binding_payload["strategy_ref"],
    )
    approval_refs = [row["approval_ref"] for row in scoped_approvals]
    policy_pairs = sorted(
        {
            (row["policy_ref"], row["policy_version"])
            for row in scoped_approvals
            if row.get("policy_ref") is not None and row.get("policy_version") is not None
        }
    )

    from sqlalchemy import and_

    policy_predicates = [
        and_(
            StrategyOrderApprovalPolicyVersion.policy_ref == policy_ref,
            StrategyOrderApprovalPolicyVersion.policy_version == version,
        )
        for policy_ref, version in policy_pairs
    ]
    policy_versions = (
        await _bounded_rows(
            session,
            StrategyOrderApprovalPolicyVersion,
            StrategyOrderApprovalPolicyVersion.owner_subject == owner_subject,
            or_(*policy_predicates),
        )
        if policy_predicates
        else []
    )
    policy_refs = sorted({row["policy_ref"] for row in policy_versions})

    categories: dict[str, list[dict[str, Any]]] = {
        "risk_rules": await _bounded_rows(
            session, RiskRule, RiskRule.user_id == owner_subject, RiskRule.paper_account_id == account_id
        ),
        "alerts": alerts,
        "alert_rules": (
            await _bounded_rows(session, AlertRule, AlertRule.user_id == owner_subject, AlertRule.id.in_(alert_rule_ids))
            if alert_rule_ids
            else []
        ),
        "alert_notifications": (
            await _bounded_rows(session, AlertNotification, AlertNotification.alert_id.in_(alert_ids))
            if alert_ids
            else []
        ),
        "strategy_target_approvals": scoped_approvals,
        "strategy_target_approval_events": (
            await _bounded_rows(session, StrategyTargetApprovalEvent, StrategyTargetApprovalEvent.approval_ref.in_(approval_refs))
            if approval_refs
            else []
        ),
        "strategy_order_approval_policy_versions": policy_versions,
        "strategy_order_approval_policy_heads": (
            await _bounded_rows(
                session,
                StrategyOrderApprovalPolicyHead,
                StrategyOrderApprovalPolicyHead.owner_subject == owner_subject,
                StrategyOrderApprovalPolicyHead.policy_ref.in_(policy_refs),
            )
            if policy_refs
            else []
        ),
        "strategy_approval_authority_epoch": await _bounded_rows(
            session, StrategyApprovalAuthorityEpoch, StrategyApprovalAuthorityEpoch.owner_subject == owner_subject
        ),
        "paper_review_reports": await _bounded_rows(
            session, PaperReviewReport, PaperReviewReport.paper_account_id == account_id
        ),
        "live_handoff_reviews": await _bounded_rows(
            session, LiveHandoffReview, LiveHandoffReview.paper_account_id == account_id
        ),
        "paper_equity_snapshots": await _bounded_rows(
            session, PaperEquitySnapshot, PaperEquitySnapshot.paper_account_id == account_id
        ),
    }
    context = {
        "schema": "afi.legacy-paper-preserved-context.v1",
        "source_account_id": account_id,
        "owner_subject": owner_subject,
        "activation": "retained_in_legacy_source_only",
        "categories": categories,
        "cursor_contract": {
            "legacy_cursor_format": "base64url_json_observed_at_id",
            "legacy_cursor_retained": "stateless_runtime_source_only",
            "target_cursor_activated": False,
        },
    }
    try:
        context_json = _canonical_json(context)
    except (TypeError, ValueError, UnicodeError):
        raise LegacyPaperImportError("LEGACY_CONTEXT_UNREADABLE") from None
    if len(context_json.encode("utf-8")) > _MAX_PRESERVED_CONTEXT_BYTES:
        raise LegacyPaperImportError("LEGACY_CONTEXT_LIMIT_EXCEEDED")
    return context, context_json, _sha256_text(context_json)


async def _receipt_for_account(session: Any, account_id: str) -> LegacyPaperImportReceipt | None:
    rows = list(
        (
            await session.execute(
                select(LegacyPaperImportReceipt)
                .where(LegacyPaperImportReceipt.legacy_account_id == account_id)
                .order_by(LegacyPaperImportReceipt.generation.desc())
                .limit(2)
            )
        )
        .scalars()
        .all()
    )
    active = [row for row in rows if row.state != "ABORTED"]
    if len(active) > 1:
        raise LegacyPaperImportError("LEGACY_IMPORT_RECEIPT_CONFLICT")
    return rows[0] if rows else None


def _require_source_receipt_matches(
    row: LegacyPaperImportReceipt,
    *,
    owner_subject: str,
    imported: Any,
    domain: Any,
    scope: Any,
    binding_sha256: str,
) -> None:
    try:
        stored_context = json.loads(row.preserved_context_json)
        stored_source = json.loads(row.source_snapshot_json)
        from bt_api_execution.paper_legacy_import import PaperLegacyImportV1

        stored_import = PaperLegacyImportV1.from_source_document(
            source_account_id=row.legacy_account_id,
            source_owner_id=row.owner_subject,
            source_document=stored_source,
            cash_currency=row.cash_currency,
            symbol_bindings=imported.symbol_bindings,
        )
        valid = (
            _canonical_json(stored_context) == row.preserved_context_json
            and _sha256_text(row.preserved_context_json) == row.preserved_context_sha256
            and _canonical_json(stored_source) == row.source_snapshot_json
            and stored_import.source_sha256 == row.source_inventory_sha256
            and row.owner_subject == owner_subject
            and row.target_import_sha256 == imported.fingerprint
            and row.target_domain_sha256 == domain.fingerprint
            and row.binding_sha256 == binding_sha256
            and row.target_scope_key == scope.key
            and row.target_account_key == scope.account_key
            and stored_import.fingerprint == imported.fingerprint
        )
    except Exception:
        valid = False
    if not valid:
        raise LegacyPaperImportError("LEGACY_IMPORT_BINDING_MISMATCH")


async def _freeze_source(
    *,
    service: Any,
    owner_subject: str,
    binding_payload: Mapping[str, Any],
    binding_sha256: str,
    scope: Any,
    domain: Any,
    imported: Any,
) -> LegacyPaperImportReceipt:
    account_id = str(binding_payload["legacy_account_id"])
    preflight = await inspect_stable_legacy_paper_account(
        service, account_id, owner_subject
    )
    if not preflight.complete or preflight.digest is None:
        raise LegacyPaperImportError("LEGACY_INVENTORY_UNAVAILABLE")
    if preflight.account.get("user_id") != owner_subject:
        raise LegacyPaperImportError("LEGACY_OWNER_MISMATCH")

    try:
        async with database.async_session_maker() as session:
            async with session.begin():
                existing = await _receipt_for_account(session, account_id)
                if existing is not None and existing.state != "ABORTED":
                    _require_source_receipt_matches(
                        existing,
                        owner_subject=owner_subject,
                        imported=imported,
                        domain=domain,
                        scope=scope,
                        binding_sha256=binding_sha256,
                    )
                    if existing.source_inventory_sha256 != preflight.digest:
                        raise LegacyPaperImportError("LEGACY_INVENTORY_CHANGED")
                    return existing

                if existing is None or existing.state == "ABORTED":
                    # Snapshot writers take this same owner row before they
                    # inspect or mutate runtime history.  The no-op UPDATE
                    # supplies the common serialization point on SQLite as
                    # well as a row lock on databases that ignore FOR UPDATE
                    # for read-only queries.
                    await session.execute(
                        update(User)
                        .where(User.id == owner_subject)
                        .values(updated_at=User.updated_at)
                    )
                    # The no-op update takes the same account-row lock as legacy
                    # writers.  A racing import that committed its fence first
                    # is handled by the read-only recovery below.
                    await session.execute(
                        update(Account)
                        .where(Account.id == account_id)
                        .values(updated_at=Account.updated_at)
                    )
                account = await session.scalar(
                    select(Account).where(Account.id == account_id).with_for_update()
                )
                if account is None:
                    raise LegacyPaperImportError("LEGACY_ACCOUNT_NOT_FOUND")
                if account.user_id != owner_subject:
                    raise LegacyPaperImportError("LEGACY_OWNER_MISMATCH")
                existing = await _receipt_for_account(session, account_id)
                if existing is not None and existing.state != "ABORTED":
                    _require_source_receipt_matches(
                        existing,
                        owner_subject=owner_subject,
                        imported=imported,
                        domain=domain,
                        scope=scope,
                        binding_sha256=binding_sha256,
                    )
                    if existing.source_inventory_sha256 != preflight.digest:
                        raise LegacyPaperImportError("LEGACY_INVENTORY_CHANGED")
                    return existing

                if await session.scalar(
                    select(LegacyPaperCutoverReceipt.id)
                    .where(LegacyPaperCutoverReceipt.legacy_account_id == account_id)
                    .limit(1)
                ) is not None:
                    raise LegacyPaperImportError("LEGACY_PAPER_ALREADY_CUT_OVER")
                if await session.scalar(
                    select(LegacyPaperWriterLease.id)
                    .where(LegacyPaperWriterLease.account_id == account_id)
                    .limit(1)
                ) is not None:
                    raise LegacyPaperImportError("LEGACY_WRITES_IN_PROGRESS")

                locked, document, document_json = await _source_snapshot_in_session(
                    session, account, owner_subject=owner_subject
                )
                if locked.digest != preflight.digest or locked.digest != imported.source_sha256:
                    raise LegacyPaperImportError("LEGACY_INVENTORY_CHANGED")
                if not any((locked.order_count, locked.position_count, locked.trade_count)):
                    raise LegacyPaperImportError("LEGACY_ACCOUNT_EMPTY")
                imported.validate_domain(scope, domain)
                await _validate_runtime_instance_account_bindings(
                    session, owner_subject=owner_subject
                )
                context, context_json, context_sha = await _preserved_context(
                    session,
                    owner_subject=owner_subject,
                    binding_payload=binding_payload,
                    document=document,
                )
                del context
                max_generation = int(
                    await session.scalar(
                        select(LegacyPaperImportReceipt.generation)
                        .where(LegacyPaperImportReceipt.legacy_account_id == account_id)
                        .order_by(LegacyPaperImportReceipt.generation.desc())
                        .limit(1)
                    )
                    or 0
                )
                now = datetime.now(timezone.utc)
                row = LegacyPaperImportReceipt(
                    legacy_account_id=account_id,
                    generation=max_generation + 1,
                    active_fence_key=account_id,
                    owner_subject=owner_subject,
                    state="PREPARED",
                    receipt_version=1,
                    source_inventory_sha256=locked.digest,
                    source_snapshot_json=document_json,
                    target_import_sha256=imported.fingerprint,
                    target_domain_sha256=domain.fingerprint,
                    binding_sha256=binding_sha256,
                    target_scope_key=scope.key,
                    target_account_key=scope.account_key,
                    cash_currency=str(binding_payload["cash_currency"]),
                    opening_cash=format(imported.opening_cash, "f"),
                    cumulative_fees=format(imported.cumulative_fees, "f"),
                    unallocated_equity_residual=format(
                        imported.unallocated_equity_residual, "f"
                    ),
                    source_order_count=locked.order_count or 0,
                    source_position_count=locked.position_count or 0,
                    source_trade_count=locked.trade_count or 0,
                    preserved_context_sha256=context_sha,
                    preserved_context_json=context_json,
                    created_at=now,
                    updated_at=now,
                )
                session.add(row)
                await session.flush()
                return row
    except LegacyPaperImportError:
        raise
    except IntegrityError:
        raced = await _read_source_receipt(account_id)
        if raced is None:
            raise LegacyPaperImportError("LEGACY_IMPORT_CONFLICT") from None
        _require_source_receipt_matches(
            raced,
            owner_subject=owner_subject,
            imported=imported,
            domain=domain,
            scope=scope,
            binding_sha256=binding_sha256,
        )
        if raced.source_inventory_sha256 != preflight.digest:
            raise LegacyPaperImportError("LEGACY_INVENTORY_CHANGED") from None
        return raced
    except Exception:
        raced = await _read_source_receipt(account_id)
        if raced is not None and raced.state != "ABORTED":
            _require_source_receipt_matches(
                raced,
                owner_subject=owner_subject,
                imported=imported,
                domain=domain,
                scope=scope,
                binding_sha256=binding_sha256,
            )
            if raced.source_inventory_sha256 == preflight.digest:
                return raced
        raise LegacyPaperImportError("LEGACY_IMPORT_STORE_UNAVAILABLE") from None


async def _read_source_receipt(account_id: str) -> LegacyPaperImportReceipt | None:
    try:
        async with database.async_session_maker() as session:
            return await _receipt_for_account(session, account_id)
    except Exception:
        raise LegacyPaperImportError("LEGACY_IMPORT_STORE_UNAVAILABLE") from None


async def _transition_source(
    *, account_id: str, owner_subject: str, source_sha256: str, target_state: str
) -> LegacyPaperImportReceipt:
    if target_state not in {"COMMITTED", "ACTIVE", "ABORTED"}:
        raise LegacyPaperImportError("INVALID_LEGACY_IMPORT_TRANSITION")
    try:
        async with database.async_session_maker() as session:
            async with session.begin():
                row = await session.scalar(
                    select(LegacyPaperImportReceipt)
                    .where(
                        LegacyPaperImportReceipt.legacy_account_id == account_id,
                        LegacyPaperImportReceipt.owner_subject == owner_subject,
                        LegacyPaperImportReceipt.source_inventory_sha256 == source_sha256,
                        LegacyPaperImportReceipt.active_fence_key == account_id,
                    )
                    .with_for_update()
                )
                if row is None:
                    raise LegacyPaperImportError("LEGACY_IMPORT_RECEIPT_NOT_FOUND")
                allowed = {
                    "PREPARED": {"COMMITTED", "ABORTED"},
                    "COMMITTED": {"ACTIVE", "ABORTED"},
                    "ACTIVE": set(),
                    "ABORTED": set(),
                }
                if row.state == target_state:
                    return row
                if target_state not in allowed.get(row.state, set()):
                    raise LegacyPaperImportError("INVALID_LEGACY_IMPORT_TRANSITION")
                row.state = target_state
                row.updated_at = _next_timestamp(row.updated_at)
                if target_state == "ABORTED":
                    row.active_fence_key = None
                await session.flush()
                return row
    except LegacyPaperImportError:
        raise
    except Exception:
        raise LegacyPaperImportError("LEGACY_IMPORT_STORE_UNAVAILABLE") from None


async def get_legacy_paper_import_receipt(
    legacy_account_id: str, owner_subject: str
) -> LegacyPaperImportReceiptView | None:
    """Return a read-only, owner-scoped receipt projection without raw rows."""

    if not _identifier(legacy_account_id) or not _identifier(owner_subject):
        raise LegacyPaperImportError("INVALID_SELECTOR")
    try:
        async with database.async_session_maker() as session:
            account_owner = await session.scalar(
                select(Account.user_id).where(Account.id == legacy_account_id)
            )
            if account_owner is None:
                raise LegacyPaperImportError("LEGACY_ACCOUNT_NOT_FOUND")
            if account_owner != owner_subject:
                raise LegacyPaperImportError("LEGACY_OWNER_MISMATCH")
            row = await _receipt_for_account(session, legacy_account_id)
            return None if row is None else _view(row)
    except LegacyPaperImportError:
        raise
    except Exception:
        raise LegacyPaperImportError("LEGACY_IMPORT_STORE_UNAVAILABLE") from None


async def inspect_legacy_paper_import_target(
    legacy_account_id: str,
    target_worker: Any,
    *,
    scope: Any,
) -> Mapping[str, Any]:
    """Read the exact configured Host target without opening a target store."""

    if not _identifier(legacy_account_id):
        raise LegacyPaperImportError("INVALID_SELECTOR")
    status = await _execution_status(
        target_worker,
        legacy_account_id,
        legacy_account_id,
        account_key=scope.account_key,
    )
    receipt = status.source_receipt
    return {
        "owner_domain_exists": status.owner_domain_exists,
        "active_account_import_state": status.active_account_import_state,
        "source_receipt": None
        if receipt is None
        else {
            "source_account_id": receipt.source_account_id,
            "source_owner_id": receipt.source_owner_id,
            "source_sha256": receipt.source_sha256,
            "state": receipt.state,
            "scope_key": receipt.scope_key,
            "account_key": receipt.account_key,
            "unallocated_equity_residual": format(
                receipt.unallocated_equity_residual, "f"
            ),
            "import_sha256": receipt.import_sha256,
            "domain_sha256": receipt.domain_sha256,
        },
    }


async def _target_call(
    target_worker: Any,
    legacy_account_id: str,
    operation: str,
    arguments: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Call the configured ServiceRead worker; never open an E store here."""

    method = getattr(target_worker, "call_paper_legacy_import", None)
    if not callable(method):
        raise LegacyPaperImportError("TARGET_IMPORT_CLIENT_UNAVAILABLE")
    try:
        reply = await method(legacy_account_id, operation, dict(arguments))
    except Exception:
        raise LegacyPaperImportError("TARGET_IMPORT_RPC_UNAVAILABLE") from None
    if (
        not isinstance(reply, Mapping)
        or set(reply) != {"ok", "code", "result"}
        or type(reply.get("ok")) is not bool
        or type(reply.get("code")) is not str
        or not isinstance(reply.get("result"), Mapping)
    ):
        raise LegacyPaperImportError("TARGET_IMPORT_REPLY_INVALID")
    if reply["ok"]:
        if reply["code"] != "OK":
            raise LegacyPaperImportError("TARGET_IMPORT_REPLY_INVALID")
        return reply["result"]

    code = reply["code"]
    if code == "IMPORT_OWNER_BUSY":
        raise LegacyPaperImportError("TARGET_WRITER_UNAVAILABLE")
    if code == "IMPORT_RESIDUAL_UNREPRESENTABLE":
        raise LegacyPaperImportError("LEGACY_EQUITY_RESIDUAL_UNREPRESENTABLE")
    if code == "IMPORT_WRITE_UNCERTAIN":
        action = operation.rsplit(".", 1)[-1].upper()
        raise LegacyPaperImportError(f"TARGET_IMPORT_{action}_UNCERTAIN")
    if code == "IMPORT_STORE_UNAVAILABLE":
        suffix = "UNCERTAIN" if operation in {
            "paper.import.prepare",
            "paper.import.activate",
            "paper.import.abort",
        } else "UNAVAILABLE"
        raise LegacyPaperImportError(f"TARGET_IMPORT_{suffix}")
    if code in {"SCOPE_DENIED", "SOURCE_OWNER_MISMATCH"}:
        raise LegacyPaperImportError("TARGET_IMPORT_BINDING_MISMATCH")
    if code in {"IMPORT_INVALID", "INVALID_ARGUMENTS"}:
        raise LegacyPaperImportError("TARGET_IMPORT_INVALID")
    if code in {"IMPORT_STATE_CONFLICT", "UNSUPPORTED_OPERATION"}:
        raise LegacyPaperImportError("TARGET_IMPORT_STATE_CONFLICT")
    raise LegacyPaperImportError("TARGET_IMPORT_RPC_FAILED")


def _execution_status_from_projection(
    projection: Mapping[str, Any], *, account_key: str
) -> Any:
    if (
        set(projection)
        != {"source_receipt", "active_account_import_state", "owner_domain_exists"}
        or type(projection.get("owner_domain_exists")) is not bool
        or type(projection.get("active_account_import_state")) not in {str, type(None)}
        or projection.get("active_account_import_state")
        not in {None, "PREPARED", "ACTIVE", "ABORTED"}
    ):
        raise LegacyPaperImportError("TARGET_IMPORT_STATUS_INVALID")
    source_value = projection["source_receipt"]
    source_receipt = None
    if source_value is not None:
        required = {
            "source_account_id",
            "source_owner_id",
            "source_sha256",
            "state",
            "scope_key",
            "account_key",
            "unallocated_equity_residual",
            "import_sha256",
            "domain_sha256",
        }
        if not isinstance(source_value, Mapping) or set(source_value) != required:
            raise LegacyPaperImportError("TARGET_IMPORT_STATUS_INVALID")
        for name in ("source_account_id", "source_owner_id", "state", "scope_key", "account_key"):
            if type(source_value[name]) is not str:
                raise LegacyPaperImportError("TARGET_IMPORT_STATUS_INVALID")
        if source_value["state"] not in {"PREPARED", "ACTIVE", "ABORTED"}:
            raise LegacyPaperImportError("TARGET_IMPORT_STATUS_INVALID")
        for name in ("source_sha256", "import_sha256", "domain_sha256"):
            value = source_value[name]
            if (
                type(value) is not str
                or len(value) != 64
                or any(character not in "0123456789abcdef" for character in value)
            ):
                raise LegacyPaperImportError("TARGET_IMPORT_STATUS_INVALID")
        try:
            residual = Decimal(source_value["unallocated_equity_residual"])
        except Exception:
            raise LegacyPaperImportError("TARGET_IMPORT_STATUS_INVALID") from None
        if not residual.is_finite() or source_value["account_key"] != account_key:
            raise LegacyPaperImportError("TARGET_IMPORT_STATUS_INVALID")
        source_fields = dict(source_value)
        source_fields["unallocated_equity_residual"] = residual
        source_receipt = SimpleNamespace(**source_fields)
    return SimpleNamespace(
        source_receipt=source_receipt,
        active_account_import_state=projection["active_account_import_state"],
        owner_domain_exists=projection["owner_domain_exists"],
    )


async def _execution_status(
    target_worker: Any,
    legacy_account_id: str,
    source_account_id: str,
    *,
    account_key: str,
) -> Any:
    if source_account_id != legacy_account_id:
        raise LegacyPaperImportError("TARGET_IMPORT_BINDING_MISMATCH")
    projection = await _target_call(
        target_worker,
        legacy_account_id,
        "paper.import.inspect_source",
        {"source_account_id": source_account_id},
    )
    return _execution_status_from_projection(projection, account_key=account_key)


def _check_execution_source_receipt(
    status: Any, *, imported: Any, domain: Any, scope: Any
) -> str | None:
    receipt = getattr(status, "source_receipt", None)
    if receipt is None:
        return None
    if receipt.state == "ABORTED":
        # Old target generations are tombstones. They are harmless only while
        # the account-wide status proves that no owner or active import remains.
        if status.active_account_import_state is not None or status.owner_domain_exists:
            raise LegacyPaperImportError("TARGET_IMPORT_BINDING_MISMATCH")
        return None
    if (
        receipt.source_account_id != imported.source_account_id
        or receipt.source_owner_id != imported.source_owner_id
        or receipt.source_sha256 != imported.source_sha256
        or receipt.account_key != scope.account_key
        or receipt.scope_key != scope.key
        or receipt.import_sha256 != imported.fingerprint
        or receipt.domain_sha256 != domain.fingerprint
        or receipt.state not in {"PREPARED", "ACTIVE", "ABORTED"}
    ):
        raise LegacyPaperImportError("TARGET_IMPORT_BINDING_MISMATCH")
    return receipt.state


def _require_active_import_row_for_cutover(
    row: Any,
    *,
    owner_subject: str,
    binding_payload: Mapping[str, Any],
    scope: Any,
    domain: Any,
) -> None:
    account_id = binding_payload["legacy_account_id"]
    residual = _decimal(getattr(row, "unallocated_equity_residual", None))
    counts = tuple(
        getattr(row, name, None)
        for name in ("source_order_count", "source_position_count", "source_trade_count")
    )
    if (
        getattr(row, "state", None) != "ACTIVE"
        or getattr(row, "receipt_version", None) != 1
        or getattr(row, "active_fence_key", None) != account_id
        or getattr(row, "legacy_account_id", None) != account_id
        or getattr(row, "owner_subject", None) != owner_subject
        or type(getattr(row, "generation", None)) is not int
        or row.generation <= 0
        or type(getattr(row, "source_inventory_sha256", None)) is not str
        or len(row.source_inventory_sha256) != 64
        or type(getattr(row, "target_import_sha256", None)) is not str
        or len(row.target_import_sha256) != 64
        or type(getattr(row, "target_domain_sha256", None)) is not str
        or row.target_domain_sha256 != domain.fingerprint
        or type(getattr(row, "binding_sha256", None)) is not str
        or type(getattr(row, "target_scope_key", None)) is not str
        or row.target_scope_key != scope.key
        or type(getattr(row, "target_account_key", None)) is not str
        or row.target_account_key != scope.account_key
        or getattr(row, "binding_sha256", None)
        != hashlib.sha256(
            _canonical_json(dict(binding_payload)).encode("utf-8")
        ).hexdigest()
        or row.cash_currency != binding_payload["cash_currency"]
        or any(type(value) is not int or value < 0 for value in counts)
        or sum(counts) <= 0
    ):
        raise LegacyPaperInventoryError("LEGACY_IMPORT_CUTOVER_BINDING_MISMATCH")
    if residual is None:
        raise LegacyPaperInventoryError("LEGACY_IMPORT_CUTOVER_BINDING_MISMATCH")
    if residual != Decimal(0):
        raise LegacyPaperInventoryError("LEGACY_EQUITY_RESIDUAL_UNREPRESENTABLE")


def _require_target_import_active_for_cutover(
    status: Any,
    *,
    imported: Any,
    domain: Any,
    scope: Any,
) -> None:
    if (
        getattr(status, "owner_domain_exists", None) is not True
        or getattr(status, "active_account_import_state", None) != "ACTIVE"
    ):
        raise LegacyPaperInventoryError("LEGACY_IMPORT_TARGET_NOT_ACTIVE")
    try:
        state = _check_execution_source_receipt(
            status, imported=imported, domain=domain, scope=scope
        )
        target_receipt = status.source_receipt
        if target_receipt is None:
            raise LegacyPaperInventoryError("LEGACY_IMPORT_TARGET_NOT_ACTIVE")
        residual = _decimal(target_receipt.unallocated_equity_residual)
    except LegacyPaperInventoryError:
        raise
    except LegacyPaperImportError as error:
        raise LegacyPaperInventoryError(error.code) from None
    if state != "ACTIVE" or residual != Decimal(0):
        raise LegacyPaperInventoryError("LEGACY_IMPORT_TARGET_NOT_ACTIVE")


def _require_imported_cutover_receipt_matches(
    cutover_receipt: Any,
    import_receipt: Any,
    *,
    owner_subject: str,
    binding_payload: Mapping[str, Any],
    binding_sha256: str,
    scope: Any,
    domain: Any,
) -> None:
    """Bind explicit cutover permission to the exact active imported baseline."""

    _require_active_import_row_for_cutover(
        import_receipt,
        owner_subject=owner_subject,
        binding_payload=binding_payload,
        scope=scope,
        domain=domain,
    )
    source_counts = (
        import_receipt.source_order_count,
        import_receipt.source_position_count,
        import_receipt.source_trade_count,
    )
    if (
        getattr(cutover_receipt, "source_kind", None) != "imported_legacy"
        or getattr(cutover_receipt, "state", None) != "ACTIVE"
        or getattr(cutover_receipt, "receipt_version", None) != 2
        or getattr(cutover_receipt, "legacy_account_id", None)
        != binding_payload["legacy_account_id"]
        or getattr(cutover_receipt, "owner_subject", None) != owner_subject
        or getattr(cutover_receipt, "source_inventory_sha256", None)
        != import_receipt.source_inventory_sha256
        or getattr(import_receipt, "binding_sha256", None) != binding_sha256
        or getattr(import_receipt, "target_domain_sha256", None)
        != binding_payload["paper_domain_sha256"]
        or getattr(cutover_receipt, "source_import_receipt_id", None) != import_receipt.id
        or getattr(cutover_receipt, "source_import_generation", None)
        != import_receipt.generation
        or getattr(cutover_receipt, "target_import_sha256", None)
        != import_receipt.target_import_sha256
        or getattr(cutover_receipt, "source_order_count", None) != source_counts[0]
        or getattr(cutover_receipt, "source_position_count", None) != source_counts[1]
        or getattr(cutover_receipt, "source_trade_count", None) != source_counts[2]
        or getattr(cutover_receipt, "binding_sha256", None) != binding_sha256
        or getattr(cutover_receipt, "paper_domain_sha256", None)
        != binding_payload["paper_domain_sha256"]
        or getattr(cutover_receipt, "scope_ref", None) != binding_payload["scope_ref"]
        or getattr(cutover_receipt, "account_ref", None) != binding_payload["account_ref"]
        or getattr(cutover_receipt, "execution_domain_ref", None)
        != binding_payload["execution_domain_ref"]
        or getattr(cutover_receipt, "strategy_ref", None) != binding_payload["strategy_ref"]
        or getattr(cutover_receipt, "initial_cash", None) != binding_payload["initial_cash"]
        or getattr(cutover_receipt, "initial_fees", None) != binding_payload["initial_fees"]
        or getattr(cutover_receipt, "fee_rate", None) != binding_payload["fee_rate"]
    ):
        raise LegacyPaperInventoryError("MANAGED_PAPER_CUTOVER_BINDING_MISMATCH")


@dataclass(frozen=True, slots=True)
class _VerifiedImportedPaperCutover:
    import_receipt: LegacyPaperImportReceipt
    imported: Any
    binding_payload: Mapping[str, Any]
    binding_sha256: str
    scope: Any
    domain: Any
    inventory: LegacyPaperInventory


async def _load_verified_import_for_cutover(
    service: Any,
    owner_subject: str,
    paper_binding: Any,
    import_binding: Any,
    *,
    target_worker: Any,
) -> _VerifiedImportedPaperCutover:
    """Revalidate the source receipt, target owner and immutable source rows."""

    try:
        from bt_api_execution.paper_legacy_import import PaperLegacyImportV1

        from app.services.service_read.client import PaperLegacyImportBinding
    except Exception:
        raise LegacyPaperInventoryError("EXECUTION_IMPORT_CONTRACT_UNAVAILABLE") from None
    if type(import_binding) is not PaperLegacyImportBinding:
        raise LegacyPaperInventoryError("LEGACY_IMPORT_BINDING_REQUIRED")
    account_id = _binding_value(paper_binding, "legacy_account_id")
    scope = _binding_value(paper_binding, "execution_scope")
    domain = _binding_value(paper_binding, "paper_owner_domain")
    if (
        import_binding.owner_subject != owner_subject
        or import_binding.legacy_account_id != account_id
        or import_binding.paper_binding is not paper_binding
        or import_binding.scope_ref != _binding_value(paper_binding, "scope_ref")
    ):
        raise LegacyPaperInventoryError("LEGACY_IMPORT_BINDING_MISMATCH")
    try:
        binding_payload = _require_server_binding(paper_binding, scope, domain)
    except LegacyPaperImportError as error:
        raise LegacyPaperInventoryError(error.code) from None
    binding_sha256 = paper_binding_fingerprint(paper_binding)
    try:
        row = await _read_source_receipt(account_id)
    except LegacyPaperImportError as error:
        raise LegacyPaperInventoryError(error.code) from None
    if row is None:
        raise LegacyPaperInventoryError("LEGACY_IMPORT_RECEIPT_NOT_FOUND")
    _require_active_import_row_for_cutover(
        row,
        owner_subject=owner_subject,
        binding_payload=binding_payload,
        scope=scope,
        domain=domain,
    )
    try:
        source_document = json.loads(row.source_snapshot_json)
        imported = PaperLegacyImportV1.from_source_document(
            source_account_id=row.legacy_account_id,
            source_owner_id=row.owner_subject,
            source_document=source_document,
            cash_currency=row.cash_currency,
            symbol_bindings=import_binding.symbol_bindings,
        )
        imported.validate_domain(scope, domain)
        _require_source_receipt_matches(
            row,
            owner_subject=owner_subject,
            imported=imported,
            domain=domain,
            scope=scope,
            binding_sha256=binding_sha256,
        )
        counts_match = (
            row.source_order_count == len(source_document["orders"])
            and row.source_position_count == len(source_document["positions"])
            and row.source_trade_count == len(source_document["trades"])
        )
        amounts_match = (
            row.opening_cash == format(imported.opening_cash, "f")
            and row.cumulative_fees == format(imported.cumulative_fees, "f")
            and _decimal(row.unallocated_equity_residual)
            == imported.unallocated_equity_residual
            and imported.unallocated_equity_residual == Decimal(0)
        )
        if not counts_match or not amounts_match:
            raise LegacyPaperInventoryError("LEGACY_IMPORT_CUTOVER_BINDING_MISMATCH")
    except LegacyPaperInventoryError:
        raise
    except Exception:
        raise LegacyPaperInventoryError("LEGACY_IMPORT_CUTOVER_BINDING_MISMATCH") from None

    inventory = await inspect_stable_legacy_paper_account(
        service, account_id, owner_subject
    )
    if (
        not inventory.complete
        or inventory.digest != row.source_inventory_sha256
        or inventory.order_count != row.source_order_count
        or inventory.position_count != row.source_position_count
        or inventory.trade_count != row.source_trade_count
    ):
        raise LegacyPaperInventoryError("MANAGED_PAPER_LEGACY_INVENTORY_CHANGED")
    try:
        status = await _execution_status(
            target_worker,
            account_id,
            account_id,
            account_key=scope.account_key,
        )
    except LegacyPaperImportError as error:
        raise LegacyPaperInventoryError(error.code) from None
    _require_target_import_active_for_cutover(
        status, imported=imported, domain=domain, scope=scope
    )
    return _VerifiedImportedPaperCutover(
        import_receipt=row,
        imported=imported,
        binding_payload=binding_payload,
        binding_sha256=binding_sha256,
        scope=scope,
        domain=domain,
        inventory=inventory,
    )


async def prepare_imported_legacy_paper_cutover(
    service: Any,
    owner_subject: str,
    paper_binding: Any,
    import_binding: Any,
    *,
    target_worker: Any,
) -> LegacyPaperCutoverReceipt:
    """Persist explicit confirmation for one already-active legacy import."""

    facts = await _load_verified_import_for_cutover(
        service,
        owner_subject,
        paper_binding,
        import_binding,
        target_worker=target_worker,
    )
    account_id = facts.import_receipt.legacy_account_id
    try:
        async with database.async_session_maker() as session:
            async with session.begin():
                account = await session.scalar(
                    select(Account).where(Account.id == account_id).with_for_update()
                )
                if account is None:
                    raise LegacyPaperInventoryError("LEGACY_ACCOUNT_NOT_FOUND")
                if account.user_id != owner_subject:
                    raise LegacyPaperInventoryError("LEGACY_OWNER_MISMATCH")

                import_row = await session.scalar(
                    select(LegacyPaperImportReceipt)
                    .where(
                        LegacyPaperImportReceipt.id == facts.import_receipt.id,
                        LegacyPaperImportReceipt.legacy_account_id == account_id,
                    )
                    .with_for_update()
                )
                if import_row is None:
                    raise LegacyPaperInventoryError("LEGACY_IMPORT_RECEIPT_NOT_FOUND")
                _require_active_import_row_for_cutover(
                    import_row,
                    owner_subject=owner_subject,
                    binding_payload=facts.binding_payload,
                    scope=facts.scope,
                    domain=facts.domain,
                )
                if (
                    import_row.id != facts.import_receipt.id
                    or import_row.source_inventory_sha256
                    != facts.import_receipt.source_inventory_sha256
                    or import_row.target_import_sha256
                    != facts.import_receipt.target_import_sha256
                    or import_row.generation != facts.import_receipt.generation
                ):
                    raise LegacyPaperInventoryError(
                        "LEGACY_IMPORT_CUTOVER_BINDING_MISMATCH"
                    )
                if await session.scalar(
                    select(LegacyPaperWriterLease.id)
                    .where(LegacyPaperWriterLease.account_id == account_id)
                    .limit(1)
                ) is not None:
                    raise LegacyPaperInventoryError("LEGACY_WRITES_IN_PROGRESS")

                locked, _, _ = await _source_snapshot_in_session(
                    session, account, owner_subject=owner_subject
                )
                if (
                    not locked.complete
                    or locked.digest != facts.import_receipt.source_inventory_sha256
                    or locked.digest != facts.inventory.digest
                    or locked.order_count != import_row.source_order_count
                    or locked.position_count != import_row.source_position_count
                    or locked.trade_count != import_row.source_trade_count
                ):
                    raise LegacyPaperInventoryError("MANAGED_PAPER_LEGACY_INVENTORY_CHANGED")

                existing = await session.scalar(
                    select(LegacyPaperCutoverReceipt).where(
                        LegacyPaperCutoverReceipt.legacy_account_id == account_id
                    )
                )
                if existing is not None:
                    _require_imported_cutover_receipt_matches(
                        existing,
                        import_row,
                        owner_subject=owner_subject,
                        binding_payload=facts.binding_payload,
                        binding_sha256=facts.binding_sha256,
                        scope=facts.scope,
                        domain=facts.domain,
                    )
                    return existing

                receipt = LegacyPaperCutoverReceipt(
                    legacy_account_id=account_id,
                    owner_subject=owner_subject,
                    state="ACTIVE",
                    receipt_version=2,
                    source_inventory_sha256=import_row.source_inventory_sha256,
                    source_kind="imported_legacy",
                    source_import_receipt_id=import_row.id,
                    source_import_generation=import_row.generation,
                    target_import_sha256=import_row.target_import_sha256,
                    binding_sha256=facts.binding_sha256,
                    paper_domain_sha256=facts.binding_payload["paper_domain_sha256"],
                    scope_ref=facts.binding_payload["scope_ref"],
                    account_ref=facts.binding_payload["account_ref"],
                    execution_domain_ref=facts.binding_payload["execution_domain_ref"],
                    strategy_ref=facts.binding_payload["strategy_ref"],
                    initial_cash=facts.binding_payload["initial_cash"],
                    initial_fees=facts.binding_payload["initial_fees"],
                    fee_rate=facts.binding_payload["fee_rate"],
                    source_order_count=import_row.source_order_count,
                    source_position_count=import_row.source_position_count,
                    source_trade_count=import_row.source_trade_count,
                )
                session.add(receipt)
                await session.flush()
                return receipt
    except LegacyPaperInventoryError:
        raise
    except IntegrityError:
        existing = await _read_cutover_receipt(account_id)
        if existing is None:
            raise LegacyPaperInventoryError("LEGACY_PAPER_CUTOVER_CONFLICT") from None
        _require_imported_cutover_receipt_matches(
            existing,
            facts.import_receipt,
            owner_subject=owner_subject,
            binding_payload=facts.binding_payload,
            binding_sha256=facts.binding_sha256,
            scope=facts.scope,
            domain=facts.domain,
        )
        return existing
    except Exception:
        raise LegacyPaperInventoryError("LEGACY_PAPER_CUTOVER_STORE_UNAVAILABLE") from None


async def require_imported_paper_cutover_qualification(
    cutover_receipt: Any,
    service: Any,
    owner_subject: str,
    paper_binding: Any,
    import_binding: Any,
    *,
    target_worker: Any,
) -> None:
    """Recheck an explicit imported cutover against source and current E owner."""

    facts = await _load_verified_import_for_cutover(
        service,
        owner_subject,
        paper_binding,
        import_binding,
        target_worker=target_worker,
    )
    _require_imported_cutover_receipt_matches(
        cutover_receipt,
        facts.import_receipt,
        owner_subject=owner_subject,
        binding_payload=facts.binding_payload,
        binding_sha256=facts.binding_sha256,
        scope=facts.scope,
        domain=facts.domain,
    )


async def prepare_managed_paper_cutover(
    service: Any,
    owner_subject: str,
    paper_binding: Any,
    import_binding: Any | None,
    *,
    target_worker: Any,
) -> Any:
    """Preserve empty cutover and explicitly confirm an ACTIVE import only."""

    account_id = _binding_value(paper_binding, "legacy_account_id")
    try:
        row = await _read_source_receipt(account_id)
    except LegacyPaperImportError as error:
        raise LegacyPaperInventoryError(error.code) from None
    if row is None:
        return await prepare_empty_account_cutover(service, owner_subject, paper_binding)
    if row.state != "ACTIVE":
        raise LegacyPaperInventoryError("LEGACY_IMPORT_NOT_ACTIVE")
    return await prepare_imported_legacy_paper_cutover(
        service,
        owner_subject,
        paper_binding,
        import_binding,
        target_worker=target_worker,
    )


async def _read_cutover_receipt(account_id: str) -> LegacyPaperCutoverReceipt | None:
    try:
        async with database.async_session_maker() as session:
            return await session.scalar(
                select(LegacyPaperCutoverReceipt).where(
                    LegacyPaperCutoverReceipt.legacy_account_id == account_id,
                    LegacyPaperCutoverReceipt.state == "ACTIVE",
                )
            )
    except Exception:
        raise LegacyPaperInventoryError("LEGACY_PAPER_CUTOVER_STORE_UNAVAILABLE") from None


async def migrate_nonempty_legacy_paper_account(
    service: Any,
    owner_subject: str,
    binding: Any,
    *,
    target_worker: Any,
    scope: Any,
    domain: Any,
    symbol_bindings: Sequence[Any],
) -> LegacyPaperImportResult:
    """Freeze and import one complete legacy account through its Host worker.

    ``binding``, ``scope``, ``domain``, and symbol bindings must come from the
    server's deployment registry. ``target_worker`` is the configured
    ServiceRead worker that calls the existing ServiceHost; this function is
    deliberately not an HTTP request parser and never trusts a client-supplied
    target owner mapping.
    """

    try:
        from bt_api_execution.paper_legacy_import import (
            LegacyPaperSymbolBindingV1,
            PaperLegacyImportV1,
        )
    except Exception:
        raise LegacyPaperImportError("EXECUTION_IMPORT_CONTRACT_UNAVAILABLE") from None
    if not _identifier(owner_subject):
        raise LegacyPaperImportError("INVALID_SELECTOR")
    binding_payload = _require_server_binding(binding, scope, domain)
    normalized_bindings = tuple(symbol_bindings)
    if any(type(item) is not LegacyPaperSymbolBindingV1 for item in normalized_bindings):
        raise LegacyPaperImportError("INVALID_SYMBOL_BINDING")
    preflight = await inspect_stable_legacy_paper_account(
        service, binding_payload["legacy_account_id"], owner_subject
    )
    if not preflight.complete or preflight.digest is None:
        raise LegacyPaperImportError("LEGACY_INVENTORY_UNAVAILABLE")
    try:
        # The second locked read below is the authority; this first document is
        # only used to reject unsupported records before any source freeze.
        import json as json_module

        service_orders = await service.order_repo.list(
            filters={"account_id": binding_payload["legacy_account_id"]},
            skip=0,
            limit=(preflight.order_count or 0) + 1,
        )
        service_positions = await service.position_repo.list(
            filters={"account_id": binding_payload["legacy_account_id"]},
            skip=0,
            limit=(preflight.position_count or 0) + 1,
        )
        service_trades = await service.trade_repo.list(
            filters={"account_id": binding_payload["legacy_account_id"]},
            skip=0,
            limit=(preflight.trade_count or 0) + 1,
        )
        source_document = {
            "schema": "afi.legacy-paper-inventory.v1",
            "account": dict(preflight.account),
            "orders": sorted((_model_row(row) for row in service_orders), key=lambda row: row["id"]),
            "positions": sorted((_model_row(row) for row in service_positions), key=lambda row: row["id"]),
            "trades": sorted((_model_row(row) for row in service_trades), key=lambda row: row["id"]),
        }
        _validate_source_pnl_projection(source_document["account"])
        preflight_json = json_module.dumps(
            source_document,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        if (
            _sha256_text(preflight_json) != preflight.digest
            or len(source_document["orders"]) != preflight.order_count
            or len(source_document["positions"]) != preflight.position_count
            or len(source_document["trades"]) != preflight.trade_count
        ):
            raise LegacyPaperImportError("LEGACY_INVENTORY_CHANGED")
        imported = PaperLegacyImportV1.from_source_document(
            source_account_id=binding_payload["legacy_account_id"],
            source_owner_id=owner_subject,
            source_document=source_document,
            cash_currency=binding_payload["cash_currency"],
            symbol_bindings=normalized_bindings,
        )
        imported.validate_domain(scope, domain)
        # Reject an instance-only or ambiguous runtime relation before the
        # target Host is queried or any import operation is issued.
        await _read_runtime_instance_account_bindings(owner_subject)
    except LegacyPaperImportError:
        raise
    except Exception:
        raise LegacyPaperImportError("LEGACY_IMPORT_NOT_REPRESENTABLE") from None

    initial_status = await _execution_status(
        target_worker,
        binding_payload["legacy_account_id"],
        imported.source_account_id,
        account_key=scope.account_key,
    )
    source_row = await _read_source_receipt(imported.source_account_id)
    if source_row is None:
        if initial_status.owner_domain_exists or initial_status.active_account_import_state is not None:
            raise LegacyPaperImportError("TARGET_ACCOUNT_ALREADY_OWNED")
        if initial_status.source_receipt is not None:
            raise LegacyPaperImportError("TARGET_IMPORT_WITHOUT_SOURCE_RECEIPT")
    elif source_row.state != "ABORTED":
        _require_source_receipt_matches(
            source_row,
            owner_subject=owner_subject,
            imported=imported,
            domain=domain,
            scope=scope,
            binding_sha256=paper_binding_fingerprint(binding),
        )

    status = await _execution_status(
        target_worker,
        binding_payload["legacy_account_id"],
        imported.source_account_id,
        account_key=scope.account_key,
    )
    if source_row is None or source_row.state == "ABORTED":
        if status.owner_domain_exists or status.active_account_import_state is not None:
            raise LegacyPaperImportError("TARGET_ACCOUNT_ALREADY_OWNED")
        if status.source_receipt is not None and status.source_receipt.state != "ABORTED":
            raise LegacyPaperImportError("TARGET_IMPORT_WITHOUT_SOURCE_RECEIPT")
    _check_execution_source_receipt(status, imported=imported, domain=domain, scope=scope)

    source_row = await _freeze_source(
        service=service,
        owner_subject=owner_subject,
        binding_payload=binding_payload,
        binding_sha256=paper_binding_fingerprint(binding),
        scope=scope,
        domain=domain,
        imported=imported,
    )
    if source_row.state == "ABORTED":
        raise LegacyPaperImportError("LEGACY_IMPORT_GENERATION_ABORTED")
    if imported.unallocated_equity_residual != Decimal(0):
        # Keep the complete source snapshot frozen for operator review, but
        # do not activate a target owner whose book cannot represent every
        # unit of the source account's marked equity.
        raise LegacyPaperImportError("LEGACY_EQUITY_RESIDUAL_UNREPRESENTABLE")

    target_state = _check_execution_source_receipt(
        await _execution_status(
            target_worker,
            binding_payload["legacy_account_id"],
            imported.source_account_id,
            account_key=scope.account_key,
        ),
        imported=imported,
        domain=domain,
        scope=scope,
    )
    if target_state is None:
        if source_row.state != "PREPARED":
            raise LegacyPaperImportError("TARGET_IMPORT_RECEIPT_MISSING")
        await _target_call(
            target_worker,
            binding_payload["legacy_account_id"],
            "paper.import.prepare",
            {"imported": imported.to_payload()},
        )
        target_state = _check_execution_source_receipt(
            await _execution_status(
                target_worker,
                binding_payload["legacy_account_id"],
                imported.source_account_id,
                account_key=scope.account_key,
            ),
            imported=imported,
            domain=domain,
            scope=scope,
        )
    if target_state == "ABORTED":
        raise LegacyPaperImportError("TARGET_IMPORT_GENERATION_ABORTED")
    if target_state not in {"PREPARED", "ACTIVE"}:
        raise LegacyPaperImportError("TARGET_IMPORT_STATUS_INVALID")

    if source_row.state == "PREPARED":
        source_row = await _transition_source(
            account_id=imported.source_account_id,
            owner_subject=owner_subject,
            source_sha256=imported.source_sha256,
            target_state="COMMITTED",
        )
    if source_row.state == "COMMITTED" and target_state == "PREPARED":
        await _target_call(
            target_worker,
            binding_payload["legacy_account_id"],
            "paper.import.activate",
            {},
        )
        target_state = _check_execution_source_receipt(
            await _execution_status(
                target_worker,
                binding_payload["legacy_account_id"],
                imported.source_account_id,
                account_key=scope.account_key,
            ),
            imported=imported,
            domain=domain,
            scope=scope,
        )
    if target_state != "ACTIVE":
        raise LegacyPaperImportError("TARGET_IMPORT_ACTIVATION_UNCERTAIN")
    final_status = await _execution_status(
        target_worker,
        binding_payload["legacy_account_id"],
        imported.source_account_id,
        account_key=scope.account_key,
    )
    if not final_status.owner_domain_exists or final_status.active_account_import_state != "ACTIVE":
        raise LegacyPaperImportError("TARGET_IMPORT_OWNER_UNVERIFIED")
    if source_row.state == "COMMITTED":
        source_row = await _transition_source(
            account_id=imported.source_account_id,
            owner_subject=owner_subject,
            source_sha256=imported.source_sha256,
            target_state="ACTIVE",
        )
    if source_row.state != "ACTIVE":
        raise LegacyPaperImportError("LEGACY_IMPORT_STATE_UNVERIFIED")
    return LegacyPaperImportResult(_view(source_row))


async def rollback_legacy_paper_import(
    legacy_account_id: str,
    owner_subject: str,
    *,
    source_inventory_sha256: str,
    target_worker: Any,
    scope: Any,
) -> LegacyPaperImportReceiptView:
    """Unfreeze only after target absence or an E PREPARED receipt is aborted.

    A committed/active owner is never rolled back.  Every uncertain status
    leaves the source fence in place.
    """

    if (
        not _identifier(legacy_account_id)
        or not _identifier(owner_subject)
        or type(source_inventory_sha256) is not str
        or len(source_inventory_sha256) != 64
        or any(char not in "0123456789abcdef" for char in source_inventory_sha256)
    ):
        raise LegacyPaperImportError("INVALID_SELECTOR")
    source_row = await _read_source_receipt(legacy_account_id)
    if source_row is None or source_row.owner_subject != owner_subject:
        raise LegacyPaperImportError("LEGACY_IMPORT_RECEIPT_NOT_FOUND")
    if source_row.source_inventory_sha256 != source_inventory_sha256:
        raise LegacyPaperImportError("LEGACY_IMPORT_BINDING_MISMATCH")
    if source_row.state == "ACTIVE":
        raise LegacyPaperImportError("ACTIVE_LEGACY_IMPORT_CANNOT_ROLL_BACK")
    if source_row.state not in {"PREPARED", "COMMITTED", "ABORTED"}:
        raise LegacyPaperImportError("INVALID_LEGACY_IMPORT_TRANSITION")
    if source_row.target_scope_key != scope.key or source_row.target_account_key != scope.account_key:
        raise LegacyPaperImportError("TARGET_SCOPE_MISMATCH")

    status = await _execution_status(
        target_worker,
        legacy_account_id,
        legacy_account_id,
        account_key=scope.account_key,
    )
    execution_state = getattr(status, "source_receipt", None)
    if execution_state is not None and (
        execution_state.scope_key != scope.key
        or execution_state.account_key != source_row.target_account_key
        or execution_state.source_sha256 != source_inventory_sha256
        or execution_state.import_sha256 != source_row.target_import_sha256
        or execution_state.domain_sha256 != source_row.target_domain_sha256
    ):
        if status.active_account_import_state is not None or status.owner_domain_exists:
            raise LegacyPaperImportError("TARGET_ACCOUNT_ALREADY_OWNED")
        execution_state = None

    if status.owner_domain_exists or status.active_account_import_state == "ACTIVE":
        raise LegacyPaperImportError("ACTIVE_LEGACY_IMPORT_CANNOT_ROLL_BACK")
    if status.active_account_import_state not in {None, "PREPARED"}:
        raise LegacyPaperImportError("TARGET_IMPORT_STATUS_INVALID")
    if execution_state is not None and execution_state.state == "PREPARED":
        await _target_call(
            target_worker,
            legacy_account_id,
            "paper.import.abort",
            {"source_sha256": source_inventory_sha256},
        )
        status = await _execution_status(
            target_worker,
            legacy_account_id,
            legacy_account_id,
            account_key=scope.account_key,
        )
        execution_state = getattr(status, "source_receipt", None)
        if (
            status.owner_domain_exists
            or status.active_account_import_state is not None
            or execution_state is None
            or execution_state.state != "ABORTED"
        ):
            raise LegacyPaperImportError("TARGET_IMPORT_ABORT_UNVERIFIED")
    elif execution_state is not None and execution_state.state != "ABORTED":
        raise LegacyPaperImportError("TARGET_IMPORT_ABORT_UNVERIFIED")
    elif status.active_account_import_state is not None:
        raise LegacyPaperImportError("TARGET_ACCOUNT_ALREADY_OWNED")

    if source_row.state != "ABORTED":
        source_row = await _transition_source(
            account_id=legacy_account_id,
            owner_subject=owner_subject,
            source_sha256=source_inventory_sha256,
            target_state="ABORTED",
        )
    return _view(source_row)


__all__ = [
    "LegacyPaperImportError",
    "LegacyPaperImportResult",
    "get_legacy_paper_import_receipt",
    "inspect_legacy_paper_import_target",
    "migrate_nonempty_legacy_paper_account",
    "rollback_legacy_paper_import",
]
