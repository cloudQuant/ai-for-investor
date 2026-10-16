from __future__ import annotations

import importlib.util
import uuid
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select, update

pytest.importorskip("bt_api_execution")

from bt_api_execution import (  # noqa: E402
    PAPER_ENVIRONMENT,
    PAPER_MODEL_REF,
    PAPER_MODEL_VERSION,
    PAPER_PROVIDER,
    PaperInstrumentV1,
    PaperOpeningPositionV1,
    PaperOwnerDomainV1,
    SqliteExecutionStore,
)
from bt_api_execution.contracts import ExecutionScope  # noqa: E402
from bt_api_execution.paper_legacy_import import LegacyPaperSymbolBindingV1  # noqa: E402

from app.db import database  # noqa: E402
from app.models.paper_trading import Account, Order, PaperTrade, Position  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.legacy_paper_import_migration import (  # noqa: E402
    LegacyPaperImportError,
    get_legacy_paper_import_receipt,
    migrate_nonempty_legacy_paper_account,
    rollback_legacy_paper_import,
)
from app.services.legacy_paper_migration import (  # noqa: E402
    LegacyPaperInventoryError,
    inspect_stable_legacy_paper_account,
    legacy_paper_writer_lease,
)
from app.services.paper_trading_service import PaperTradingService  # noqa: E402

_SOURCE_ACCOUNT_ID = str(uuid.UUID("af120000-0000-4000-8000-000000000001"))
_SOURCE_OWNER_ID = str(uuid.UUID("af120000-0000-4000-8000-000000000002"))
_ORDER_ID = str(uuid.UUID("af120000-0000-4000-8000-000000000003"))
_TRADE_ID = str(uuid.UUID("af120000-0000-4000-8000-000000000004"))
_POSITION_ID = str(uuid.UUID("af120000-0000-4000-8000-000000000005"))
_ACCOUNT_REF = "afi12-simulation-account-v1"
_DOMAIN_REF = "afi12-execution-domain-v1"
_STRATEGY_REF = "afi12-strategy-v1"
_EXPERIMENT_REF = "afi12-experiment-v1"
_QUOTE_SOURCE_REF = "afi12-quotes-v1"
_INSTRUMENT = "BTC-USDT"
_LEGACY_SYMBOL = "BTC/USDT"


def _domain() -> tuple[ExecutionScope, PaperOwnerDomainV1]:
    scope = ExecutionScope(
        PAPER_PROVIDER,
        PAPER_ENVIRONMENT,
        _ACCOUNT_REF,
        _STRATEGY_REF,
    )
    domain = PaperOwnerDomainV1(
        execution_domain_ref=_DOMAIN_REF,
        simulation_account_ref=_ACCOUNT_REF,
        experiment_ref=_EXPERIMENT_REF,
        strategy_ref=_STRATEGY_REF,
        model_ref=PAPER_MODEL_REF,
        model_version=PAPER_MODEL_VERSION,
        quote_source_ref=_QUOTE_SOURCE_REF,
        cash_currency="USDT",
        initial_cash=Decimal("89.9"),
        initial_fees=Decimal("0.1"),
        fee_rate=Decimal("0.01"),
        fee_quantum=Decimal("0.01"),
        max_quote_age_ns=30_000_000_000,
        instruments=(
            PaperInstrumentV1(
                _INSTRUMENT,
                "afi12-btc-usdt-v1",
                "BTC",
                "USDT",
                Decimal("0.001"),
                Decimal("0.01"),
            ),
        ),
        opening_positions=(
            PaperOpeningPositionV1(_INSTRUMENT, Decimal("1"), Decimal("10")),
        ),
    )
    return scope, domain


def _binding(domain: PaperOwnerDomainV1) -> SimpleNamespace:
    return SimpleNamespace(
        mount="application.orders",
        scope_ref="afi12-submit-scope-v1",
        query_scope_ref="afi12-query-scope-v1",
        legacy_account_id=_SOURCE_ACCOUNT_ID,
        account_ref=_ACCOUNT_REF,
        execution_domain_ref=_DOMAIN_REF,
        strategy_ref=_STRATEGY_REF,
        experiment_ref=_EXPERIMENT_REF,
        model_ref=PAPER_MODEL_REF,
        model_version=PAPER_MODEL_VERSION,
        quote_source_ref=_QUOTE_SOURCE_REF,
        cash_currency="USDT",
        paper_domain_sha256=domain.fingerprint,
        initial_cash=domain.initial_cash,
        initial_fees=domain.initial_fees,
        fee_rate=domain.fee_rate,
        fee_quantum=domain.fee_quantum,
        max_quote_age_ns=domain.max_quote_age_ns,
        instrument_metadata_versions={_INSTRUMENT: "afi12-btc-usdt-v1"},
        opening_positions=tuple(item.to_payload() for item in domain.opening_positions),
    )


def _load_revision(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _install_source_migrations() -> None:
    from alembic.migration import MigrationContext as _MigrationContext
    from alembic.operations import Operations as _Operations

    backend_root = Path(__file__).resolve().parents[1]
    versions = backend_root / "alembic" / "versions"
    cutover = _load_revision(
        "afi12_test_legacy_paper_cutover_revision",
        versions / "20261016_legacy_paper_cutover.py",
    )
    importer = _load_revision(
        "afi12_test_legacy_paper_import_revision",
        versions / "20261016_legacy_paper_import.py",
    )

    def apply(sync_connection: Any) -> None:
        for table in (
            "legacy_paper_import_receipts",
            "legacy_paper_writer_leases",
            "legacy_paper_cutover_receipts",
        ):
            sync_connection.exec_driver_sql(f"DROP TABLE IF EXISTS {table}")
        context = _MigrationContext.configure(sync_connection)
        with _Operations.context(context):
            cutover.upgrade()
            importer.upgrade()

    async with database.engine.begin() as connection:
        await connection.run_sync(apply)


async def _seed_account(
    *,
    total_equity: float = 99.9,
    profit_loss: float = -0.1,
    profit_loss_pct: float = -0.1,
    pending_order: bool = False,
) -> None:
    async with database.async_session_maker() as session:
        async with session.begin():
            session.add(
                User(
                    id=_SOURCE_OWNER_ID,
                    username="afi12-source-owner",
                    email="afi12-source-owner@example.test",
                    hashed_password="synthetic-test-only-unused",
                )
            )
            session.add(
                Account(
                    id=_SOURCE_ACCOUNT_ID,
                    user_id=_SOURCE_OWNER_ID,
                    name="Legacy nonempty paper account",
                    initial_cash=100.0,
                    current_cash=100.0 if pending_order else 89.9,
                    total_equity=100.0 if pending_order else total_equity,
                    profit_loss=0.0 if pending_order else profit_loss,
                    profit_loss_pct=0.0 if pending_order else profit_loss_pct,
                    commission_rate=0.01,
                    slippage_rate=0.0,
                    is_active=True,
                )
            )
            if pending_order:
                session.add(
                    Order(
                        id=_ORDER_ID,
                        account_id=_SOURCE_ACCOUNT_ID,
                        symbol=_LEGACY_SYMBOL,
                        order_type="market",
                        side="buy",
                        size=1.0,
                        price=None,
                        stop_price=None,
                        limit_price=None,
                        filled_size=0.0,
                        avg_fill_price=0.0,
                        status="pending",
                        commission=0.0,
                        slippage=0.0,
                    )
                )
                return

            session.add(
                Order(
                    id=_ORDER_ID,
                    account_id=_SOURCE_ACCOUNT_ID,
                    symbol=_LEGACY_SYMBOL,
                    order_type="market",
                    side="buy",
                    size=1.0,
                    price=None,
                    stop_price=None,
                    limit_price=None,
                    filled_size=1.0,
                    avg_fill_price=10.0,
                    status="filled",
                    commission=0.1,
                    slippage=0.0,
                )
            )
            session.add(
                Position(
                    id=_POSITION_ID,
                    account_id=_SOURCE_ACCOUNT_ID,
                    symbol=_LEGACY_SYMBOL,
                    size=1.0,
                    avg_price=10.0,
                    market_value=10.0,
                    margin_value=0.0,
                    multiplier=1.0,
                    margin_rate=1.0,
                    commission_rate=0.01,
                    commission_amount=0.0,
                    unrealized_pnl=0.0,
                    unrealized_pnl_pct=0.0,
                    entry_price=10.0,
                )
            )
            session.add(
                PaperTrade(
                    id=_TRADE_ID,
                    account_id=_SOURCE_ACCOUNT_ID,
                    order_id=_ORDER_ID,
                    symbol=_LEGACY_SYMBOL,
                    side="buy",
                    size=1.0,
                    price=10.0,
                    commission=0.1,
                    slippage=0.0,
                    pnl=0.0,
                    pnl_pct=0.0,
                )
            )


def _target(tmp_path: Path) -> tuple[SqliteExecutionStore, ExecutionScope, PaperOwnerDomainV1]:
    scope, domain = _domain()
    return SqliteExecutionStore(tmp_path / "afi12-execution.sqlite3"), scope, domain


@pytest.mark.asyncio
async def test_nonempty_import_conserves_source_and_target_without_fabricating_execution_facts(
    tmp_path: Path,
) -> None:
    await _install_source_migrations()
    await _seed_account()
    service = PaperTradingService()
    before = await inspect_stable_legacy_paper_account(service, _SOURCE_ACCOUNT_ID, _SOURCE_OWNER_ID)
    assert before.complete and before.digest is not None

    target_store, scope, domain = _target(tmp_path)
    try:
        result = await migrate_nonempty_legacy_paper_account(
            service,
            _SOURCE_OWNER_ID,
            _binding(domain),
            target_store=target_store,
            scope=scope,
            domain=domain,
            symbol_bindings=(LegacyPaperSymbolBindingV1(_LEGACY_SYMBOL, _INSTRUMENT),),
        )
        assert result.receipt.state == "ACTIVE"
        assert result.legacy_ledger_retained_read_only is True
        assert result.imported_rows_are_exchange_facts is False
        assert result.old_rules_approvals_alerts_activated is False
        assert result.receipt.source_inventory_sha256 == before.digest
        after = await inspect_stable_legacy_paper_account(service, _SOURCE_ACCOUNT_ID, _SOURCE_OWNER_ID)
        assert after.complete and after.digest == before.digest

        target_connection = target_store._connection
        changes_before_get = target_connection.total_changes
        receipt = await get_legacy_paper_import_receipt(_SOURCE_ACCOUNT_ID, _SOURCE_OWNER_ID)
        assert receipt is not None and receipt.state == "ACTIVE"
        assert receipt.source_inventory_sha256 == before.digest
        assert not hasattr(receipt, "source_snapshot_json")
        imported = target_store.get_paper_legacy_import(scope)
        assert imported is not None and imported.state == "ACTIVE"
        assert imported.imported.origin == "imported_legacy"
        assert imported.imported.source_sha256 == before.digest
        assert target_store.read_paper_book(scope).cash == Decimal("89.9")
        book = target_store.read_paper_book(scope)
        assert book.cumulative_fees == Decimal("0.1")
        assert [(row.instrument, row.quantity, row.average_cost) for row in book.positions] == [
            (_INSTRUMENT, Decimal("1"), Decimal("10"))
        ]
        assert book.receipt_count == 0
        assert book.execution_cursor == 0
        assert target_connection.total_changes == changes_before_get
        assert _ORDER_ID in imported.imported.source_document_json

        with pytest.raises(LegacyPaperInventoryError):
            async with legacy_paper_writer_lease(_SOURCE_ACCOUNT_ID):
                pytest.fail("a legacy writer entered after the source fence committed")
    finally:
        target_store.close()


@pytest.mark.asyncio
async def test_nonzero_equity_residual_stays_frozen_until_safe_abort(tmp_path: Path) -> None:
    await _install_source_migrations()
    await _seed_account(total_equity=100.4, profit_loss=0.4, profit_loss_pct=0.4)
    service = PaperTradingService()
    target_store, scope, domain = _target(tmp_path)
    try:
        with pytest.raises(LegacyPaperImportError) as caught:
            await migrate_nonempty_legacy_paper_account(
                service,
                _SOURCE_OWNER_ID,
                _binding(domain),
                target_store=target_store,
                scope=scope,
                domain=domain,
                symbol_bindings=(LegacyPaperSymbolBindingV1(_LEGACY_SYMBOL, _INSTRUMENT),),
            )
        assert caught.value.code == "LEGACY_EQUITY_RESIDUAL_UNREPRESENTABLE"
        frozen = await get_legacy_paper_import_receipt(_SOURCE_ACCOUNT_ID, _SOURCE_OWNER_ID)
        assert frozen is not None and frozen.state == "PREPARED"
        assert frozen.unallocated_equity_residual == "0.5"
        status = target_store.inspect_paper_legacy_import_account(
            scope, source_account_id=_SOURCE_ACCOUNT_ID
        )
        assert status.source_receipt is None
        assert status.owner_domain_exists is False
        assert status.active_account_import_state is None

        aborted = await rollback_legacy_paper_import(
            _SOURCE_ACCOUNT_ID,
            _SOURCE_OWNER_ID,
            source_inventory_sha256=frozen.source_inventory_sha256,
            target_store=target_store,
            scope=scope,
        )
        assert aborted.state == "ABORTED"
        async with legacy_paper_writer_lease(_SOURCE_ACCOUNT_ID):
            async with database.async_session_maker() as session:
                async with session.begin():
                    await session.execute(
                        update(Account)
                        .where(Account.id == _SOURCE_ACCOUNT_ID)
                        .values(current_cash=Account.current_cash)
                    )
    finally:
        target_store.close()


@pytest.mark.asyncio
async def test_unresolved_order_is_rejected_without_freeze_or_target_owner(tmp_path: Path) -> None:
    await _install_source_migrations()
    await _seed_account(pending_order=True)
    service = PaperTradingService()
    target_store, scope, domain = _target(tmp_path)
    try:
        with pytest.raises(LegacyPaperImportError) as caught:
            await migrate_nonempty_legacy_paper_account(
                service,
                _SOURCE_OWNER_ID,
                _binding(domain),
                target_store=target_store,
                scope=scope,
                domain=domain,
                symbol_bindings=(LegacyPaperSymbolBindingV1(_LEGACY_SYMBOL, _INSTRUMENT),),
            )
        assert caught.value.code == "LEGACY_IMPORT_NOT_REPRESENTABLE"
        assert await get_legacy_paper_import_receipt(_SOURCE_ACCOUNT_ID, _SOURCE_OWNER_ID) is None
        status = target_store.inspect_paper_legacy_import_account(
            scope, source_account_id=_SOURCE_ACCOUNT_ID
        )
        assert status.source_receipt is None
        assert status.owner_domain_exists is False
        assert status.active_account_import_state is None
        async with database.async_session_maker() as session:
            pending = await session.scalar(select(Order).where(Order.id == _ORDER_ID))
        assert pending is not None and pending.status == "pending"
    finally:
        target_store.close()


@pytest.mark.asyncio
async def test_inconsistent_account_pnl_is_rejected_before_source_freeze(tmp_path: Path) -> None:
    await _install_source_migrations()
    await _seed_account(profit_loss=5.0, profit_loss_pct=5.0)
    service = PaperTradingService()
    target_store, scope, domain = _target(tmp_path)
    try:
        with pytest.raises(LegacyPaperImportError) as caught:
            await migrate_nonempty_legacy_paper_account(
                service,
                _SOURCE_OWNER_ID,
                _binding(domain),
                target_store=target_store,
                scope=scope,
                domain=domain,
                symbol_bindings=(LegacyPaperSymbolBindingV1(_LEGACY_SYMBOL, _INSTRUMENT),),
            )
        assert caught.value.code == "LEGACY_PNL_NOT_RECONCILED"
        assert await get_legacy_paper_import_receipt(_SOURCE_ACCOUNT_ID, _SOURCE_OWNER_ID) is None
        assert target_store.get_paper_legacy_import(scope) is None
    finally:
        target_store.close()
