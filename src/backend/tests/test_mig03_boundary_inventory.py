"""Focused tests for the accepted AFI MIG03 in-place boundary reader."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
from contextlib import suppress
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import app.services.mig03_boundary_inventory as boundary_inventory
from app.db.database import Base
from app.models.approved_target_http_operation import ApprovedTargetHttpOperation
from app.models.legacy_paper_import import LegacyPaperImportReceipt
from app.models.paper_runtime import PaperEquitySnapshot
from app.models.paper_trading import Account, Order, OrderStatus, PaperTrade, Position
from app.models.service_order_operation import ServiceOrderOperation
from app.models.strategy_target_approval import (
    StrategyTargetApproval,
    StrategyTargetApprovalEvent,
)
from app.services.mig03_boundary_inventory import (
    CODE_BOUNDARY_NOT_CONSERVED,
    CODE_INVALID_BOUNDARY_SCOPE,
    AfiMigrationBoundaryError,
    assert_afi_state_conserved,
    capture_afi_boundary,
    stop_paper_snapshot_writers,
)
from app.services.paper_runtime_scheduler import PaperRuntimeSnapshotScheduler

_SCOPE = "afi-mig03-scope"
_ACCOUNT_REF = "afi-mig03-live-account-ref"
_STRATEGY = "afi-mig03-strategy-ref"
_PAPER_ACCOUNT = "afi-mig03-paper-account"
_PAPER_INSTANCE = "afi-mig03-paper-instance"
_SOURCE_REF = "sqlite://mig03-synthetic-afi"
_CONFIG_SHA256 = "a" * 64
_HASH_1 = "1" * 64
_HASH_2 = "2" * 64
_HASH_3 = "3" * 64


def _models() -> tuple[type, ...]:
    return (
        ServiceOrderOperation,
        StrategyTargetApproval,
        StrategyTargetApprovalEvent,
        ApprovedTargetHttpOperation,
        Account,
        Position,
        Order,
        PaperTrade,
        PaperEquitySnapshot,
        LegacyPaperImportReceipt,
    )


def _seed_database(path: Path):
    engine = create_engine(f"sqlite:///{path}")
    try:
        Base.metadata.create_all(engine, tables=[model.__table__ for model in _models()])
        with Session(engine) as session:
            session.add(
                ServiceOrderOperation(
                    owner_subject="owner-mig03",
                    principal_ref="principal-mig03",
                    actor_ref="actor-mig03",
                    delegate_ref="",
                    operation_kind="manual_order",
                    operation_key_sha256=_HASH_1,
                    request_sha256=_HASH_2,
                    intent_id="execution-intent-manual-1",
                    scope_ref=_SCOPE,
                    account_ref=_ACCOUNT_REF,
                    manual_book_ref="manual-book-mig03",
                    last_service_code="OK",
                    last_record_state="FILLED",
                )
            )
            approval = StrategyTargetApproval(
                approval_ref="approval-mig03-1",
                approval_version=1,
                record_version=2,
                state="APPROVED",
                owner_subject="owner-mig03",
                principal_ref="principal-mig03",
                actor_ref="actor-mig03",
                delegate_ref="",
                scope_ref=_SCOPE,
                execution_domain_ref="execution-domain-mig03",
                account_ref=_ACCOUNT_REF,
                strategy_ref=_STRATEGY,
                strategy_version=4,
                membership_version=7,
                membership_sha256=_HASH_3,
                target_ref="target-mig03",
                target_version=9,
                target_sha256=_HASH_1,
                canonical_target_json='{"symbol":"SYNTH-USD","side":"BUY"}',
                policy_ref="policy-mig03",
                policy_version=5,
                policy_sha256=_HASH_2,
                approved_by_subject="approver-mig03",
                approved_by_principal_ref="approver-principal-mig03",
                approved_by_actor_ref="approver-actor-mig03",
                approved_by_delegate_ref="",
                approved_at_ns=100,
                expires_at_ns=10_000,
                operation_key_sha256=_HASH_3,
                operation_request_sha256=_HASH_1,
                intent_id="execution-intent-approved-1",
                operation_reserved_at_ns=101,
            )
            session.add(approval)
            session.flush()
            session.add_all(
                [
                    StrategyTargetApprovalEvent(
                        approval_ref=approval.approval_ref,
                        approval_version=1,
                        record_version=1,
                        event_type="APPROVED",
                        owner_subject="owner-mig03",
                        actor_subject="approver-mig03",
                        principal_ref="approver-principal-mig03",
                        actor_ref="approver-actor-mig03",
                        delegate_ref="",
                        target_sha256=_HASH_1,
                        occurred_at_ns=100,
                        reason_code="approved",
                    ),
                    StrategyTargetApprovalEvent(
                        approval_ref=approval.approval_ref,
                        approval_version=1,
                        record_version=2,
                        event_type="OPERATION_RESERVED",
                        owner_subject="owner-mig03",
                        actor_subject="actor-mig03",
                        principal_ref="principal-mig03",
                        actor_ref="actor-mig03",
                        delegate_ref="",
                        target_sha256=_HASH_1,
                        occurred_at_ns=101,
                        operation_key_sha256=_HASH_3,
                        intent_id="execution-intent-approved-1",
                    ),
                ]
            )
            session.add(
                ApprovedTargetHttpOperation(
                    owner_subject="owner-mig03",
                    principal_ref="principal-mig03",
                    actor_ref="actor-mig03",
                    delegate_ref="",
                    operation_key_sha256=_HASH_3,
                    request_sha256=_HASH_1,
                    approval_ref=approval.approval_ref,
                    approval_version=1,
                    target_sha256=_HASH_1,
                    intent_id="execution-intent-approved-1",
                    selector_ref="selector-mig03",
                    scope_ref=_SCOPE,
                    account_ref=_ACCOUNT_REF,
                    strategy_ref=_STRATEGY,
                )
            )
            session.add(
                Account(
                    id=_PAPER_ACCOUNT,
                    user_id="user-mig03",
                    name="MIG03 paper account",
                    initial_cash=100_000.0,
                    current_cash=99_899.9,
                    total_equity=99_999.9,
                    profit_loss=-0.1,
                )
            )
            session.add(
                Position(
                    id="paper-position-mig03-1",
                    account_id=_PAPER_ACCOUNT,
                    symbol="SYNTH-USD",
                    size=2.0,
                    avg_price=50.0,
                    market_value=100.0,
                    margin_value=0.0,
                    multiplier=1.0,
                    margin_rate=1.0,
                    commission_rate=0.001,
                    commission_amount=0.1,
                    unrealized_pnl=0.0,
                    unrealized_pnl_pct=0.0,
                    entry_price=50.0,
                )
            )
            session.add_all(
                [
                    Order(
                        id="paper-order-mig03-filled",
                        account_id=_PAPER_ACCOUNT,
                        symbol="SYNTH-USD",
                        order_type="limit",
                        side="buy",
                        size=2.0,
                        price=50.0,
                        filled_size=2.0,
                        avg_fill_price=50.0,
                        status=OrderStatus.FILLED.value,
                        commission=0.1,
                        slippage=0.0,
                    ),
                    Order(
                        id="paper-order-mig03-unresolved",
                        account_id=_PAPER_ACCOUNT,
                        symbol="SYNTH-USD",
                        order_type="limit",
                        side="sell",
                        size=1.0,
                        price=51.0,
                        filled_size=0.0,
                        avg_fill_price=0.0,
                        status=OrderStatus.PENDING.value,
                    ),
                ]
            )
            session.add(
                PaperTrade(
                    id="paper-trade-mig03-1",
                    account_id=_PAPER_ACCOUNT,
                    order_id="paper-order-mig03-filled",
                    symbol="SYNTH-USD",
                    side="buy",
                    size=2.0,
                    price=50.0,
                    commission=0.1,
                    slippage=0.0,
                    pnl=0.0,
                    pnl_pct=0.0,
                )
            )
            session.add(
                PaperEquitySnapshot(
                    id="paper-equity-mig03-1",
                    user_id="user-mig03",
                    workspace_id="workspace-mig03",
                    unit_id="unit-mig03",
                    instance_id=_PAPER_INSTANCE,
                    paper_account_id=_PAPER_ACCOUNT,
                    source="mark_to_market",
                    total_equity=99_999.9,
                    cash=99_899.9,
                    position_value=100.0,
                    unrealized_pnl=0.0,
                    realized_pnl=0.0,
                    metadata_json={"run_ref": "paper-run-mig03"},
                )
            )
            session.commit()
        return engine


    except BaseException:
        with suppress(BaseException):
            engine.dispose()
        raise
def _capture(session: Session):
    return capture_afi_boundary(
        session,
        scope_ref=_SCOPE,
        account_ref=_ACCOUNT_REF,
        strategy_refs=(_STRATEGY,),
        account_paper_accounts={_ACCOUNT_REF: _PAPER_ACCOUNT},
        paper_account_instances={_PAPER_ACCOUNT: _PAPER_INSTANCE},
        source_ref=_SOURCE_REF,
        configuration_sha256=_CONFIG_SHA256,
    )


def _insert_valid_import_receipt(engine) -> str:
    from app.services.legacy_paper_migration import _model_row

    receipt_id = "mig03-import-receipt-1"
    with Session(engine) as session:
        account = session.get(Account, _PAPER_ACCOUNT)
        assert account is not None
        source_document = {
            "schema": "afi.legacy-paper-inventory.v1",
            "account": _model_row(account),
            "orders": [
                _model_row(row)
                for row in session.scalars(
                    select(Order).where(Order.account_id == _PAPER_ACCOUNT).order_by(Order.id)
                )
            ],
            "positions": [
                _model_row(row)
                for row in session.scalars(
                    select(Position)
                    .where(Position.account_id == _PAPER_ACCOUNT)
                    .order_by(Position.id)
                )
            ],
            "trades": [
                _model_row(row)
                for row in session.scalars(
                    select(PaperTrade)
                    .where(PaperTrade.account_id == _PAPER_ACCOUNT)
                    .order_by(PaperTrade.id)
                )
            ],
        }
        source_json = json.dumps(
            source_document,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        context_json = json.dumps(
            {
                "schema": "afi.legacy-paper-preserved-context.v1",
                "source_account_id": _PAPER_ACCOUNT,
                "owner_subject": account.user_id,
                "activation": "retained_in_legacy_source_only",
                "categories": {
                    name: []
                    for name in (
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
                    )
                },
                "cursor_contract": {
                    "legacy_cursor_format": "base64url_json_observed_at_id",
                    "legacy_cursor_retained": "stateless_runtime_source_only",
                    "target_cursor_activated": False,
                },
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        now = datetime.now(timezone.utc)
        session.add(
            LegacyPaperImportReceipt(
                id=receipt_id,
                legacy_account_id=_PAPER_ACCOUNT,
                generation=1,
                active_fence_key=_PAPER_ACCOUNT,
                owner_subject=account.user_id,
                state="ACTIVE",
                receipt_version=1,
                source_inventory_sha256=hashlib.sha256(
                    source_json.encode("utf-8")
                ).hexdigest(),
                source_snapshot_json=source_json,
                target_import_sha256=_HASH_1,
                target_domain_sha256=_HASH_2,
                binding_sha256=_HASH_3,
                target_scope_key="execution-scope-mig03",
                target_account_key="execution-account-mig03",
                cash_currency="USD",
                opening_cash="89.9",
                cumulative_fees="0.1",
                unallocated_equity_residual="0",
                source_order_count=len(source_document["orders"]),
                source_position_count=len(source_document["positions"]),
                source_trade_count=len(source_document["trades"]),
                preserved_context_sha256=hashlib.sha256(
                    context_json.encode("utf-8")
                ).hexdigest(),
                preserved_context_json=context_json,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()
    return receipt_id


def test_mig03_afi_amount_projection_roundtrips_typed_numeric_values() -> None:
    original_float = 100_000.0
    adjacent_float = math.nextafter(original_float, math.inf)
    original_projection = boundary_inventory._normal_value(original_float)
    adjacent_projection = boundary_inventory._normal_value(adjacent_float)

    assert original_projection == {"float_hex": original_float.hex()}
    assert adjacent_projection == {"float_hex": adjacent_float.hex()}
    assert original_projection != adjacent_projection
    assert boundary_inventory._decimal_text(
        boundary_inventory._decimal(original_projection)
    ) == "100000"
    assert boundary_inventory._decimal_text(
        boundary_inventory._decimal(adjacent_projection)
    ) == "100000.00000000001"

    decimal_projection = boundary_inventory._normal_value(Decimal("99.900"))
    assert decimal_projection == {"decimal": "99.9"}
    assert boundary_inventory._decimal_text(
        boundary_inventory._decimal(decimal_projection)
    ) == "99.9"
    nested_projection = boundary_inventory._normal_value(
        {"amounts": (Decimal("2.500"), original_float)}
    )
    assert nested_projection == {
        "amounts": [{"decimal": "2.5"}, {"float_hex": original_float.hex()}]
    }

    for unsupported in (
        True,
        object(),
        {"float_hex": "0x1p+16"},
        {"float_hex": original_float.hex(), "extra": 1},
        {"decimal": "99.900"},
    ):
        with pytest.raises(AfiMigrationBoundaryError) as invalid_amount:
            boundary_inventory._decimal(unsupported)
        assert invalid_amount.value.code == boundary_inventory.CODE_BOUNDARY_READ_FAILED


def test_mig03_afi_inventory_preserves_operation_approval_fills_fees_and_positions(
    tmp_path: Path,
) -> None:
    path = tmp_path / "afi-mig03.sqlite3"
    engine = _seed_database(path)
    try:
        before_bytes = hashlib.sha256(path.read_bytes()).hexdigest()
        with Session(engine) as source:
            before = _capture(source)
            source_account = source.get(Account, _PAPER_ACCOUNT)
            assert source_account is not None
            original_updated_at = source_account.updated_at
        assert original_updated_at is not None
        updated_at_column = Account.__table__.c.updated_at
        assert updated_at_column.onupdate is not None
        assert callable(updated_at_column.onupdate.arg)
        with Session(engine) as reopened:
            after = _capture(reopened)
        assert_afi_state_conserved(before, after)
        assert before.operation_approval.row_count == 5
        assert before.paper_ledger.row_count == 6
        assert hashlib.sha256(path.read_bytes()).hexdigest() == before_bytes
        assert (
            "paper_account_ref",
            _ACCOUNT_REF,
            "paper_account",
            _PAPER_ACCOUNT,
        ) in before.identity_links
        assert (
            "afi_operations.manual_key",
            _HASH_1,
            "execution.intent_id",
            "execution-intent-manual-1",
        ) in before.identity_links
        assert (
            "afi_approval_ref",
            "approval-mig03-1",
            "execution.intent_id",
            "execution-intent-approved-1",
        ) in before.identity_links
        assert "paper-order-mig03-unresolved" in before.unresolved_ids
        assert before.reservation_ids == (
            "execution-intent-approved-1",
            "execution-intent-manual-1",
        )
        assert (
            f"account:{_PAPER_ACCOUNT}:current_cash",
            "99899.9",
        ) in before.amounts
        assert (
            f"trade:paper-trade-mig03-1:commission",
            "0.1",
        ) in before.amounts
        assert before.positions == ((f"{_PAPER_ACCOUNT}:SYNTH-USD:paper-position-mig03-1", "2"),)
        assert (
            "paper_equity_snapshot",
            "paper-equity-mig03-1",
            "paper_run_ref",
            "paper-run-mig03",
        ) in before.identity_links
        sdk_participants = before.boundary_participants()
        assert tuple(item["participant_id"] for item in sdk_participants) == (
            "afi_operations",
            "afi_paper",
        )
        assert all(item["configuration_sha256"] == _CONFIG_SHA256 for item in sdk_participants)
        assert sdk_participants[1]["schema_sha256"] == before.paper_ledger.schema_sha256

        with Session(engine) as changed:
            account = changed.get(Account, _PAPER_ACCOUNT)
            assert account is not None
            account.current_cash += 1.0
            changed.commit()
        with Session(engine) as drifted:
            drifted_account = drifted.get(Account, _PAPER_ACCOUNT)
            assert drifted_account is not None
            assert drifted_account.updated_at != original_updated_at
            changed_snapshot = _capture(drifted)
        with pytest.raises(AfiMigrationBoundaryError) as nonconserved:
            assert_afi_state_conserved(before, changed_snapshot)
        assert nonconserved.value.code == CODE_BOUNDARY_NOT_CONSERVED

        with Session(engine) as restore:
            account = restore.get(Account, _PAPER_ACCOUNT)
            assert account is not None
            account.current_cash = 99_899.9
            # This test changes and then restores a deliberately drifted row.
            # SQLAlchemy's onupdate is proven above; explicitly restore the
            # seeded timestamp so the recovered state is byte-for-byte logical
            # conservation, rather than silently exempting timestamps.
            account.updated_at = original_updated_at
            restore.commit()
        with Session(engine) as recovered:
            recovered_account = recovered.get(Account, _PAPER_ACCOUNT)
            assert recovered_account is not None
            assert recovered_account.updated_at == original_updated_at
            recovered_snapshot = _capture(recovered)
        assert_afi_state_conserved(before, recovered_snapshot)

        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE INDEX mig03_boundary_schema_drift "
                "ON paper_trading_orders(account_id)"
            )
        with Session(engine) as schema_changed:
            changed_schema = _capture(schema_changed)
        assert changed_schema.paper_ledger.schema_sha256 != before.paper_ledger.schema_sha256
        with pytest.raises(AfiMigrationBoundaryError) as schema_drift:
            assert_afi_state_conserved(before, changed_schema)
        assert schema_drift.value.code == CODE_BOUNDARY_NOT_CONSERVED
    finally:
        engine.dispose()


def test_mig03_afi_inventory_rejects_unbound_paper_snapshot_account(tmp_path: Path) -> None:
    engine = _seed_database(tmp_path / "afi-mig03-unbound.sqlite3")
    try:
        with Session(engine) as session:
            snapshot = session.get(PaperEquitySnapshot, "paper-equity-mig03-1")
            assert snapshot is not None
            snapshot.paper_account_id = None
            session.commit()
        with Session(engine) as session:
            with pytest.raises(AfiMigrationBoundaryError) as unbound:
                _capture(session)
        assert unbound.value.code == CODE_INVALID_BOUNDARY_SCOPE
    finally:
        engine.dispose()


def test_mig03_afi_inventory_conserves_import_receipt_identity_and_financial_facts(
    tmp_path: Path,
) -> None:
    engine = _seed_database(tmp_path / "afi-mig03-import-receipt.sqlite3")
    try:
        receipt_id = _insert_valid_import_receipt(engine)
        with Session(engine) as before_session:
            before = _capture(before_session)
        assert before.paper_ledger.row_count == 7
        assert (
            "paper_import_receipt",
            receipt_id,
            "paper_account",
            _PAPER_ACCOUNT,
        ) in before.identity_links
        assert (
            "paper_import_receipt",
            receipt_id,
            "paper_import_target_scope",
            "execution-scope-mig03",
        ) in before.identity_links
        assert (
            f"legacy_import_receipt:{receipt_id}:cumulative_fees",
            "0.1",
        ) in before.amounts

        with Session(engine) as changed_session:
            receipt = changed_session.get(LegacyPaperImportReceipt, receipt_id)
            assert receipt is not None
            receipt.binding_sha256 = "4" * 64
            changed_session.commit()
        with Session(engine) as changed_session:
            changed = _capture(changed_session)
        with pytest.raises(AfiMigrationBoundaryError) as changed_receipt:
            assert_afi_state_conserved(before, changed)
        assert changed_receipt.value.code == CODE_BOUNDARY_NOT_CONSERVED

        with Session(engine) as incomplete_session:
            receipt = incomplete_session.get(LegacyPaperImportReceipt, receipt_id)
            assert receipt is not None
            incomplete_context = json.dumps(
                {
                    "schema": "afi.legacy-paper-preserved-context.v1",
                    "source_account_id": _PAPER_ACCOUNT,
                    "owner_subject": "owner-mig03",
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
            receipt.preserved_context_json = incomplete_context
            receipt.preserved_context_sha256 = hashlib.sha256(
                incomplete_context.encode("utf-8")
            ).hexdigest()
            incomplete_session.commit()
        with Session(engine) as incomplete_session:
            with pytest.raises(AfiMigrationBoundaryError) as incomplete_context_error:
                _capture(incomplete_session)
        assert incomplete_context_error.value.code == CODE_INVALID_BOUNDARY_SCOPE

        with Session(engine) as missing_session:
            receipt = missing_session.get(LegacyPaperImportReceipt, receipt_id)
            assert receipt is not None
            missing_session.delete(receipt)
            missing_session.commit()
        with Session(engine) as missing_session:
            missing = _capture(missing_session)
        with pytest.raises(AfiMigrationBoundaryError) as missing_receipt:
            assert_afi_state_conserved(before, missing)
        assert missing_receipt.value.code == CODE_BOUNDARY_NOT_CONSERVED
    finally:
        engine.dispose()


def test_mig03_afi_inventory_rejects_http_operation_with_mismatched_approval(
    tmp_path: Path,
) -> None:
    engine = _seed_database(tmp_path / "afi-mig03-mismatched-approval.sqlite3")
    try:
        with Session(engine) as session:
            operation = session.scalar(
                select(ApprovedTargetHttpOperation).where(
                    ApprovedTargetHttpOperation.approval_ref == "approval-mig03-1"
                )
            )
            assert operation is not None
            operation.intent_id = "different-execution-intent"
            session.commit()
        with Session(engine) as session:
            with pytest.raises(AfiMigrationBoundaryError) as mismatch:
                _capture(session)
        assert mismatch.value.code == CODE_INVALID_BOUNDARY_SCOPE
    finally:
        engine.dispose()


def test_mig03_afi_inventory_rejects_invalid_approval_event_order(tmp_path: Path) -> None:
    engine = _seed_database(tmp_path / "afi-mig03-invalid-event-order.sqlite3")
    try:
        with Session(engine) as session:
            event = session.scalar(
                select(StrategyTargetApprovalEvent).where(
                    StrategyTargetApprovalEvent.approval_ref == "approval-mig03-1",
                    StrategyTargetApprovalEvent.record_version == 1,
                )
            )
            assert event is not None
            event.event_type = "REVOKED"
            session.commit()
        with Session(engine) as session:
            with pytest.raises(AfiMigrationBoundaryError) as invalid_chain:
                _capture(session)
        assert invalid_chain.value.code == CODE_INVALID_BOUNDARY_SCOPE
    finally:
        engine.dispose()


def test_mig03_afi_inventory_rejects_oversized_row_before_orm_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _seed_database(tmp_path / "afi-mig03-oversized-row.sqlite3")
    try:
        with Session(engine) as seed:
            snapshot = seed.get(PaperEquitySnapshot, "paper-equity-mig03-1")
            assert snapshot is not None
            snapshot.metadata_json = {"run_ref": "paper-run-mig03", "large": "x" * 4096}
            seed.commit()

        monkeypatch.setattr(boundary_inventory, "_MAX_BOUNDARY_BYTES", 1024)
        with Session(engine) as session:
            original_execute = session.execute
            entity_statement = select(PaperEquitySnapshot)
            entity_query_started = False

            def execute(statement, *args, **kwargs):
                nonlocal entity_query_started
                if statement is entity_statement:
                    entity_query_started = True
                return original_execute(statement, *args, **kwargs)

            monkeypatch.setattr(session, "execute", execute)
            with pytest.raises(AfiMigrationBoundaryError) as oversized:
                boundary_inventory._query_rows(
                    session,
                    PaperEquitySnapshot,
                    entity_statement,
                    boundary_inventory._InventoryReadBudget(),
                )
        assert oversized.value.code == boundary_inventory.CODE_BOUNDARY_READ_FAILED
        assert not entity_query_started
    finally:
        engine.dispose()


def test_mig03_afi_scheduler_shutdown_waits_for_all_snapshot_tasks() -> None:
    async def run() -> None:
        scheduler = PaperRuntimeSnapshotScheduler()
        started = asyncio.Event()

        async def held_snapshot(_user_id: str, _instance_id: str) -> None:
            started.set()
            await asyncio.Event().wait()

        scheduler._run = held_snapshot  # type: ignore[method-assign]
        scheduler.ensure_running("user-mig03", _PAPER_INSTANCE)
        await asyncio.wait_for(started.wait(), timeout=1.0)
        receipt = await stop_paper_snapshot_writers(scheduler)
        assert receipt.tasks_before == 1
        assert receipt.stopped_task_names == (f"paper-runtime-snapshot:{_PAPER_INSTANCE}",)
        assert receipt.tasks_after == 0

    asyncio.run(run())
