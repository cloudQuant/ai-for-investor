from __future__ import annotations

import importlib.util
import uuid
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session

pytest.importorskip("bt_api_execution")

from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope  # noqa: E402
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
from bt_api_execution.service_paper_legacy_import import PaperLegacyImportService  # noqa: E402

from app.api.deps import get_current_user  # noqa: E402
from app.api.service_read import configure_service_read  # noqa: E402
from app.db import database  # noqa: E402
from app.main import app  # noqa: E402
from app.models.legacy_paper_import import LegacyPaperImportReceipt  # noqa: E402
from app.models.legacy_paper_cutover import LegacyPaperCutoverReceipt  # noqa: E402
from app.models.paper_trading import Account, Order, PaperTrade, Position  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.legacy_paper_import_migration import (  # noqa: E402
    LegacyPaperImportError,
    _require_active_import_row_for_cutover,
    get_legacy_paper_import_receipt,
    migrate_nonempty_legacy_paper_account,
    prepare_managed_paper_cutover,
    rollback_legacy_paper_import,
)
from app.services.legacy_paper_migration import (  # noqa: E402
    LegacyPaperInventoryError,
    inspect_stable_legacy_paper_account,
    legacy_paper_writer_lease,
    paper_binding_fingerprint,
    _paper_binding_payload,
    require_active_paper_cutover_receipt,
)
from app.services.managed_paper_adapter import (  # noqa: E402
    ManagedPaperOrderAdapter,
    ManagedPaperOrderError,
)
from app.schemas.paper_trading import OrderRequest  # noqa: E402
from app.services.mig03_boundary_inventory import (  # noqa: E402
    assert_afi_state_conserved,
    capture_afi_boundary,
)
from app.services.paper_trading_service import PaperTradingService  # noqa: E402
from app.services.service_read.access import (  # noqa: E402
    ReadAccess,
    ServiceReadAccessDirectory,
)
from app.services.service_read.client import (  # noqa: E402
    PaperLegacyImportBinding,
    PaperSubmitBinding,
)

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
    imported_cutover = _load_revision(
        "afi13_test_legacy_paper_import_cutover_revision",
        versions / "20261017_legacy_paper_import_cutover.py",
    )

    def apply(sync_connection: Any) -> None:
        for table in (
            "legacy_paper_cutover_receipts",
            "legacy_paper_import_receipts",
            "legacy_paper_writer_leases",
        ):
            sync_connection.exec_driver_sql(f"DROP TABLE IF EXISTS {table}")
        context = _MigrationContext.configure(sync_connection)
        with _Operations.context(context):
            cutover.upgrade()
            importer.upgrade()
            imported_cutover.upgrade()

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


async def _seed_empty_account() -> None:
    async with database.async_session_maker() as session:
        async with session.begin():
            session.add(
                User(
                    id=_SOURCE_OWNER_ID,
                    username="afi12-source-owner-empty",
                    email="afi12-source-owner-empty@example.test",
                    hashed_password="synthetic-test-only-unused",
                )
            )
            session.add(
                Account(
                    id=_SOURCE_ACCOUNT_ID,
                    user_id=_SOURCE_OWNER_ID,
                    name="Legacy account filled by old matcher",
                    initial_cash=100.0,
                    current_cash=100.0,
                    total_equity=100.0,
                    profit_loss=0.0,
                    profit_loss_pct=0.0,
                    commission_rate=0.01,
                    slippage_rate=0.0,
                    is_active=True,
                )
            )


async def _capture_afi_boundary_for_import_test():
    async with database.engine.connect() as connection:
        def capture(sync_connection):
            with Session(sync_connection) as session:
                return capture_afi_boundary(
                    session,
                    scope_ref="afi12-mig03-scope-v1",
                    account_ref=_ACCOUNT_REF,
                    strategy_refs=(_STRATEGY_REF,),
                    account_paper_accounts={_ACCOUNT_REF: _SOURCE_ACCOUNT_ID},
                    paper_account_instances={_SOURCE_ACCOUNT_ID: "afi12-paper-instance-v1"},
                    source_ref="sqlite://afi12-mig03-synthetic-source",
                    configuration_sha256="a" * 64,
                )

        return await connection.run_sync(capture)


def _receipt_projection(receipt: LegacyPaperImportReceipt) -> tuple[Any, ...]:
    return tuple(
        getattr(receipt, column.key)
        for column in LegacyPaperImportReceipt.__table__.columns
    )


async def _read_receipt_projection(receipt_id: str) -> tuple[Any, ...]:
    async with database.async_session_maker() as session:
        receipt = await session.get(LegacyPaperImportReceipt, receipt_id)
        assert receipt is not None
        return _receipt_projection(receipt)


class _TargetWorker:
    """Exercise migration through the same typed worker-call contract as HTTP."""

    def __init__(self, store: SqliteExecutionStore, scope: ExecutionScope, domain: PaperOwnerDomainV1):
        wire_scope = WireScope(
            _DOMAIN_REF,
            account_ref=_ACCOUNT_REF,
            strategy_ref=_STRATEGY_REF,
        )
        self._wire_scope = wire_scope
        self._service = PaperLegacyImportService(
            store,
            {wire_scope: scope},
            domain,
            writer_id="afi12-unit-host-owner-v1",
        )

    async def call_paper_legacy_import(
        self, legacy_account_id: str, operation: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        assert legacy_account_id == _SOURCE_ACCOUNT_ID
        reply = self._service.handle(
            operation,
            scope=self._wire_scope,
            arguments=arguments,
        )
        return {
            "ok": reply["ok"],
            "code": reply["code"],
            "result": dict(reply["result"]),
        }

    async def read_account(self, account_ref: str, *, currency: str | None = None) -> Any:
        raise AssertionError("legacy import API must not read a separate account projection")

    async def read_order(self, scope_ref: str, intent_id: str) -> Any:
        raise AssertionError("legacy import API must not read arbitrary target orders")

    async def read_strategy_health(self, scope_ref: str) -> Any:
        raise AssertionError("legacy import API must not read unrelated strategy health")

    async def submit_paper_order(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("legacy import API must not submit a paper order")


class _ManagedPaperTargetWorker(_TargetWorker):
    """Keep import status real while stubbing only the order presentation edge."""

    def __init__(self, store: SqliteExecutionStore, scope: ExecutionScope, domain: PaperOwnerDomainV1):
        super().__init__(store, scope, domain)
        self.submitted: list[tuple[str, dict[str, Any]]] = []
        self.read_intents: list[str] = []

    async def submit_paper_order(
        self, scope_ref: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        self.submitted.append((scope_ref, dict(arguments)))
        return {"ok": True, "code": "OK", "result": {}}

    async def read_order(self, scope_ref: str, intent_id: str) -> Any:
        from types import SimpleNamespace

        self.read_intents.append(intent_id)
        return SimpleNamespace(
            intent_id=intent_id,
            state="ACKED",
            quality="fresh",
            filled_quantity=Decimal("0"),
            average_price=None,
            cumulative_commission=Decimal("0"),
            is_terminal=False,
            unknown_reason=None,
            review_required=False,
            updated_at_ns=1,
            detail_code=None,
        )


def _target(
    tmp_path: Path,
) -> tuple[SqliteExecutionStore, _TargetWorker, ExecutionScope, PaperOwnerDomainV1]:
    scope, domain = _domain()
    store = SqliteExecutionStore(tmp_path / "afi12-execution.sqlite3")
    return store, _TargetWorker(store, scope, domain), scope, domain


@pytest.mark.asyncio
async def test_nonempty_import_conserves_source_and_target_without_fabricating_execution_facts(
    tmp_path: Path,
) -> None:
    await _install_source_migrations()
    await _seed_account()
    service = PaperTradingService()
    before = await inspect_stable_legacy_paper_account(service, _SOURCE_ACCOUNT_ID, _SOURCE_OWNER_ID)
    assert before.complete and before.digest is not None

    target_store, target_worker, scope, domain = _target(tmp_path)
    try:
        result = await migrate_nonempty_legacy_paper_account(
            service,
            _SOURCE_OWNER_ID,
            _binding(domain),
            target_worker=target_worker,
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
async def test_active_import_requires_explicit_managed_cutover_before_order_read_or_submit(
    tmp_path: Path,
) -> None:
    await _install_source_migrations()
    await _seed_account()
    service = PaperTradingService()
    scope, domain = _domain()
    target_store = SqliteExecutionStore(tmp_path / "afi13-import-cutover-execution.sqlite3")
    worker = _ManagedPaperTargetWorker(target_store, scope, domain)
    try:
        directory = _http_import_directory(worker, scope, domain)
        access = directory.resolve_paper_submit_account(_SOURCE_OWNER_ID, _SOURCE_ACCOUNT_ID)
        paper_binding = access.paper_submit_bindings[_SOURCE_ACCOUNT_ID]
        import_binding = access.paper_legacy_import_bindings[_SOURCE_ACCOUNT_ID]
        imported = await migrate_nonempty_legacy_paper_account(
            service,
            _SOURCE_OWNER_ID,
            paper_binding,
            target_worker=worker,
            scope=scope,
            domain=domain,
            symbol_bindings=import_binding.symbol_bindings,
        )
        assert imported.receipt.state == "ACTIVE"

        adapter = ManagedPaperOrderAdapter(
            legacy_service_factory=lambda: service,
            access_resolver=lambda subject, account_id: (
                access,
                access.paper_submit_bindings[account_id],
            ),
        )
        request = OrderRequest(
            account_id=_SOURCE_ACCOUNT_ID,
            symbol=_INSTRUMENT,
            order_type="market",
            side="buy",
            size=0.25,
        )

        with pytest.raises(ManagedPaperOrderError) as unconfirmed:
            await adapter.submit_manual(
                subject=_SOURCE_OWNER_ID,
                request=request,
                idempotency_key="afi13-imported-before-confirm",
            )
        assert unconfirmed.value.code == "LEGACY_PAPER_CUTOVER_REQUIRED"
        with pytest.raises(LegacyPaperInventoryError) as unconfirmed_read:
            await require_active_paper_cutover_receipt(
                _SOURCE_ACCOUNT_ID,
                _SOURCE_OWNER_ID,
                paper_binding,
                service_factory=lambda: service,
                import_binding=import_binding,
                target_worker=worker,
            )
        assert unconfirmed_read.value.code == "LEGACY_PAPER_CUTOVER_REQUIRED"
        assert worker.submitted == []

        cutover = await adapter.prepare_cutover(
            subject=_SOURCE_OWNER_ID,
            legacy_account_id=_SOURCE_ACCOUNT_ID,
        )
        assert cutover["state"] == "ACTIVE"
        assert cutover["receipt_version"] == 2
        assert cutover["source_counts"] == {"orders": 1, "positions": 1, "trades": 1}
        async with database.async_session_maker() as session:
            persisted = await session.scalar(
                select(LegacyPaperCutoverReceipt).where(
                    LegacyPaperCutoverReceipt.legacy_account_id == _SOURCE_ACCOUNT_ID
                )
            )
        assert persisted is not None
        assert persisted.source_kind == "imported_legacy"
        assert persisted.source_import_receipt_id == imported.receipt.receipt_id
        assert persisted.source_import_generation == imported.receipt.generation
        assert persisted.target_import_sha256 == imported.receipt.target_import_sha256

        result = await adapter.submit_manual(
            subject=_SOURCE_OWNER_ID,
            request=request,
            idempotency_key="afi13-imported-after-confirm",
        )
        assert result["state"] == "ACKED"
        assert result["submission_acknowledged"] is True
        assert worker.submitted[0][0] == paper_binding.scope_ref
        assert worker.submitted[0][1]["position_effect"] == "OPEN"
        assert worker.read_intents[0] == result["intent_id"]

        readback = await adapter.read_order(
            subject=_SOURCE_OWNER_ID,
            legacy_account_id=_SOURCE_ACCOUNT_ID,
            intent_id=result["intent_id"],
        )
        assert readback["state"] == "ACKED"
        assert worker.read_intents[-1] == result["intent_id"]
        source_after = await inspect_stable_legacy_paper_account(
            service, _SOURCE_ACCOUNT_ID, _SOURCE_OWNER_ID
        )
        assert source_after.digest == imported.receipt.source_inventory_sha256
        assert target_store.read_paper_book(scope).cash == Decimal("89.9")
        assert target_store.read_paper_book(scope).receipt_count == 0
    finally:
        target_store.close()


@pytest.mark.asyncio
async def test_empty_account_keeps_version_one_managed_cutover(
    tmp_path: Path,
) -> None:
    from dataclasses import replace

    await _install_source_migrations()
    empty_owner = str(uuid.UUID("af130000-0000-4000-8000-000000000002"))
    empty_account = str(uuid.UUID("af130000-0000-4000-8000-000000000001"))
    async with database.async_session_maker() as session:
        async with session.begin():
            session.add(
                User(
                    id=empty_owner,
                    username="afi13-empty-paper-owner",
                    email="afi13-empty-paper-owner@example.test",
                    hashed_password="synthetic-test-only-unused",
                )
            )
            session.add(
                Account(
                    id=empty_account,
                    user_id=empty_owner,
                    name="Legacy empty paper account",
                    initial_cash=100.0,
                    current_cash=100.0,
                    total_equity=100.0,
                    profit_loss=0.0,
                    profit_loss_pct=0.0,
                    commission_rate=0.01,
                    slippage_rate=0.0,
                    is_active=True,
                )
            )

    scope, imported_domain = _domain()
    empty_domain = replace(
        imported_domain,
        initial_cash=Decimal("100"),
        initial_fees=Decimal("0"),
        opening_positions=(),
    )
    binding = _binding(empty_domain)
    binding.legacy_account_id = empty_account
    service = PaperTradingService()
    receipt = await prepare_managed_paper_cutover(
        service,
        empty_owner,
        binding,
        None,
        target_worker=object(),
    )

    assert receipt.source_kind == "empty_account"
    assert receipt.receipt_version == 1
    assert receipt.source_import_receipt_id is None
    assert receipt.source_import_generation is None
    assert receipt.target_import_sha256 is None
    assert (
        receipt.source_order_count,
        receipt.source_position_count,
        receipt.source_trade_count,
    ) == (0, 0, 0)
    validated = await require_active_paper_cutover_receipt(
        empty_account,
        empty_owner,
        binding,
    )
    assert validated.id == receipt.id


@pytest.mark.asyncio
async def test_managed_cutover_rejects_nonactive_import_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.legacy_paper_import_migration as import_migration

    async def prepared_receipt(account_id: str) -> Any:
        assert account_id == _SOURCE_ACCOUNT_ID
        return SimpleNamespace(state="PREPARED")

    monkeypatch.setattr(import_migration, "_read_source_receipt", prepared_receipt)
    _, domain = _domain()
    with pytest.raises(LegacyPaperInventoryError) as caught:
        await prepare_managed_paper_cutover(
            None,
            _SOURCE_OWNER_ID,
            _binding(domain),
            None,
            target_worker=object(),
        )
    assert caught.value.code == "LEGACY_IMPORT_NOT_ACTIVE"


def test_import_cutover_preflight_rejects_wrong_owner_domain_scope_and_residual() -> None:
    scope, domain = _domain()
    binding = _binding(domain)
    payload = _paper_binding_payload(binding)
    row_fields = {
        "state": "ACTIVE",
        "receipt_version": 1,
        "active_fence_key": _SOURCE_ACCOUNT_ID,
        "legacy_account_id": _SOURCE_ACCOUNT_ID,
        "owner_subject": _SOURCE_OWNER_ID,
        "generation": 1,
        "source_inventory_sha256": "a" * 64,
        "target_import_sha256": "b" * 64,
        "target_domain_sha256": domain.fingerprint,
        "binding_sha256": paper_binding_fingerprint(binding),
        "target_scope_key": scope.key,
        "target_account_key": scope.account_key,
        "cash_currency": "USDT",
        "source_order_count": 1,
        "source_position_count": 1,
        "source_trade_count": 1,
        "unallocated_equity_residual": "0",
    }

    _require_active_import_row_for_cutover(
        SimpleNamespace(**row_fields),
        owner_subject=_SOURCE_OWNER_ID,
        binding_payload=payload,
        scope=scope,
        domain=domain,
    )
    invalid_facts = (
        ({"owner_subject": "different-owner"}, _SOURCE_OWNER_ID, scope, domain,
         "LEGACY_IMPORT_CUTOVER_BINDING_MISMATCH"),
        ({"target_scope_key": "different-scope"}, _SOURCE_OWNER_ID, scope, domain,
         "LEGACY_IMPORT_CUTOVER_BINDING_MISMATCH"),
        ({"target_domain_sha256": "c" * 64}, _SOURCE_OWNER_ID, scope, domain,
         "LEGACY_IMPORT_CUTOVER_BINDING_MISMATCH"),
        ({"state": "PREPARED"}, _SOURCE_OWNER_ID, scope, domain,
         "LEGACY_IMPORT_CUTOVER_BINDING_MISMATCH"),
        ({"unallocated_equity_residual": "0.5"}, _SOURCE_OWNER_ID, scope, domain,
         "LEGACY_EQUITY_RESIDUAL_UNREPRESENTABLE"),
        ({}, "different-owner", scope, domain,
         "LEGACY_IMPORT_CUTOVER_BINDING_MISMATCH"),
        ({}, _SOURCE_OWNER_ID, SimpleNamespace(key="different-scope", account_key=scope.account_key), domain,
         "LEGACY_IMPORT_CUTOVER_BINDING_MISMATCH"),
    )
    for changes, owner, candidate_scope, candidate_domain, expected_code in invalid_facts:
        with pytest.raises(LegacyPaperInventoryError) as caught:
            _require_active_import_row_for_cutover(
                SimpleNamespace(**{**row_fields, **changes}),
                owner_subject=owner,
                binding_payload=payload,
                scope=candidate_scope,
                domain=candidate_domain,
            )
        assert caught.value.code == expected_code


@pytest.mark.asyncio
async def test_real_legacy_matcher_is_fenced_and_receipt_stays_conserved_after_import(
    tmp_path: Path,
) -> None:
    await _install_source_migrations()
    await _seed_empty_account()
    service = PaperTradingService()

    # Exercise the complete old producer entry to create the source fill,
    # position, fees, and account cash before the existing AFI12 import.
    filled = await service.submit_order(
        _SOURCE_ACCOUNT_ID,
        _LEGACY_SYMBOL,
        "market",
        "buy",
        1.0,
    )
    assert filled.status == "filled"
    assert filled.filled_size == 1.0
    assert filled.avg_fill_price == 10.0
    source_before = await inspect_stable_legacy_paper_account(
        service, _SOURCE_ACCOUNT_ID, _SOURCE_OWNER_ID
    )
    assert source_before.complete and source_before.order_count == 1
    assert source_before.position_count == 1 and source_before.trade_count == 1

    target_store, target_worker, scope, domain = _target(tmp_path)
    try:
        migrated = await migrate_nonempty_legacy_paper_account(
            service,
            _SOURCE_OWNER_ID,
            _binding(domain),
            target_worker=target_worker,
            scope=scope,
            domain=domain,
            symbol_bindings=(LegacyPaperSymbolBindingV1(_LEGACY_SYMBOL, _INSTRUMENT),),
        )
        assert migrated.receipt.state == "ACTIVE"
        assert migrated.receipt.source_inventory_sha256 == source_before.digest
        assert migrated.legacy_ledger_retained_read_only is True
        assert migrated.imported_rows_are_exchange_facts is False
        receipt_before = await _read_receipt_projection(migrated.receipt.receipt_id)

        before_boundary = await _capture_afi_boundary_for_import_test()
        assert before_boundary.paper_ledger.row_count == 5
        assert (
            "paper_import_receipt",
            migrated.receipt.receipt_id,
            "paper_account",
            _SOURCE_ACCOUNT_ID,
        ) in before_boundary.identity_links
        assert (
            "paper_import_receipt",
            migrated.receipt.receipt_id,
            "paper_import_source_sha256",
            source_before.digest,
        ) in before_boundary.identity_links

        with pytest.raises(LegacyPaperInventoryError) as denied_submit:
            await service.submit_order(
                _SOURCE_ACCOUNT_ID,
                _LEGACY_SYMBOL,
                "market",
                "buy",
                1.0,
            )
        assert denied_submit.value.code == "MANAGED_PAPER_LEGACY_ACCOUNT_FENCED"

        account = await service.account_repo.get_by_id(_SOURCE_ACCOUNT_ID)
        assert account is not None
        with pytest.raises(LegacyPaperInventoryError) as denied_process:
            await service._process_order(filled.id, _SOURCE_ACCOUNT_ID, account)
        assert denied_process.value.code == "MANAGED_PAPER_LEGACY_ACCOUNT_FENCED"

        source_after = await inspect_stable_legacy_paper_account(
            service, _SOURCE_ACCOUNT_ID, _SOURCE_OWNER_ID
        )
        assert source_after.complete and source_after.digest == source_before.digest
        after_boundary = await _capture_afi_boundary_for_import_test()
        assert_afi_state_conserved(before_boundary, after_boundary)
        assert await _read_receipt_projection(migrated.receipt.receipt_id) == receipt_before

        imported = target_store.get_paper_legacy_import(scope)
        assert imported is not None and imported.state == "ACTIVE"
        assert target_store.read_paper_book(scope).cash == Decimal("89.9")
        assert target_store.read_paper_book(scope).cumulative_fees == Decimal("0.1")
        assert [
            (row.instrument, row.quantity, row.average_cost)
            for row in target_store.read_paper_book(scope).positions
        ] == [(_INSTRUMENT, Decimal("1"), Decimal("10"))]
    finally:
        target_store.close()


@pytest.mark.asyncio
async def test_nonzero_equity_residual_stays_frozen_until_safe_abort(tmp_path: Path) -> None:
    await _install_source_migrations()
    await _seed_account(total_equity=100.4, profit_loss=0.4, profit_loss_pct=0.4)
    service = PaperTradingService()
    target_store, target_worker, scope, domain = _target(tmp_path)
    try:
        with pytest.raises(LegacyPaperImportError) as caught:
            await migrate_nonempty_legacy_paper_account(
                service,
                _SOURCE_OWNER_ID,
                _binding(domain),
                target_worker=target_worker,
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
            target_worker=target_worker,
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
    target_store, target_worker, scope, domain = _target(tmp_path)
    try:
        with pytest.raises(LegacyPaperImportError) as caught:
            await migrate_nonempty_legacy_paper_account(
                service,
                _SOURCE_OWNER_ID,
                _binding(domain),
                target_worker=target_worker,
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
    target_store, target_worker, scope, domain = _target(tmp_path)
    try:
        with pytest.raises(LegacyPaperImportError) as caught:
            await migrate_nonempty_legacy_paper_account(
                service,
                _SOURCE_OWNER_ID,
                _binding(domain),
                target_worker=target_worker,
                scope=scope,
                domain=domain,
                symbol_bindings=(LegacyPaperSymbolBindingV1(_LEGACY_SYMBOL, _INSTRUMENT),),
            )
        assert caught.value.code == "LEGACY_PNL_NOT_RECONCILED"
        assert await get_legacy_paper_import_receipt(_SOURCE_ACCOUNT_ID, _SOURCE_OWNER_ID) is None
        assert target_store.get_paper_legacy_import(scope) is None
    finally:
        target_store.close()


@pytest.mark.asyncio
async def test_authenticated_http_import_uses_configured_worker_and_keeps_source_read_only(
    tmp_path: Path,
    client: Any,
) -> None:
    await _install_source_migrations()
    await _seed_account()
    service = PaperTradingService()
    target_store, target_worker, scope, domain = _target(tmp_path)
    configure_service_read(_http_import_directory(target_worker, scope, domain))
    app.dependency_overrides[get_current_user] = lambda: _http_user(_SOURCE_OWNER_ID)
    try:
        before = await inspect_stable_legacy_paper_account(
            service, _SOURCE_ACCOUNT_ID, _SOURCE_OWNER_ID
        )
        unconfirmed = await client.post(
            f"/api/v1/legacy-paper-imports/accounts/{_SOURCE_ACCOUNT_ID}/migrate",
            json={"confirmed": False},
        )
        assert unconfirmed.status_code == 422

        inspected = await client.get(
            f"/api/v1/legacy-paper-imports/accounts/{_SOURCE_ACCOUNT_ID}"
        )
        assert inspected.status_code == 200
        assert inspected.json()["source_inventory"]["sha256"] == before.digest
        assert inspected.json()["source_receipt"] is None
        assert inspected.json()["target"]["source_receipt"] is None

        migrated = await client.post(
            f"/api/v1/legacy-paper-imports/accounts/{_SOURCE_ACCOUNT_ID}/migrate",
            json={"confirmed": True},
        )
        assert migrated.status_code == 200, migrated.text
        migrated_body = migrated.json()
        assert migrated_body["receipt"]["state"] == "ACTIVE"
        assert migrated_body["receipt"]["source_inventory_sha256"] == before.digest
        assert migrated_body["receipt"]["source_order_count"] == 1
        assert migrated_body["receipt"]["source_position_count"] == 1
        assert migrated_body["receipt"]["source_trade_count"] == 1
        assert migrated_body["receipt"]["unallocated_equity_residual"] == "0.0"
        assert migrated_body["legacy_ledger_retained_read_only"] is True
        assert migrated_body["imported_rows_are_exchange_facts"] is False
        assert migrated_body["old_rules_approvals_alerts_activated"] is False
        assert "source_snapshot_json" not in migrated_body["receipt"]
        assert "source_document_json" not in migrated_body["receipt"]

        after = await inspect_stable_legacy_paper_account(
            service, _SOURCE_ACCOUNT_ID, _SOURCE_OWNER_ID
        )
        assert after.complete and after.digest == before.digest
        target_book = target_store.read_paper_book(scope)
        assert target_book.cash == Decimal("89.9")
        assert target_book.cumulative_fees == Decimal("0.1")
        assert [
            (row.instrument, row.quantity, row.average_cost)
            for row in target_book.positions
        ] == [(_INSTRUMENT, Decimal("1"), Decimal("10"))]
        assert target_book.receipt_count == 0
        assert target_book.execution_cursor == 0

        denied = await client.post(
            f"/api/v1/legacy-paper-imports/accounts/{_SOURCE_ACCOUNT_ID}/migrate",
            json={"confirmed": True, "owner_subject": "client-selected"},
        )
        assert denied.status_code == 422
    finally:
        configure_service_read(None)
        target_store.close()


@pytest.mark.asyncio
async def test_http_residual_refusal_requires_digest_bound_source_rollback(
    tmp_path: Path,
    client: Any,
) -> None:
    await _install_source_migrations()
    await _seed_account(total_equity=100.4, profit_loss=0.4, profit_loss_pct=0.4)
    target_store, target_worker, scope, domain = _target(tmp_path)
    configure_service_read(_http_import_directory(target_worker, scope, domain))
    app.dependency_overrides[get_current_user] = lambda: _http_user(_SOURCE_OWNER_ID)
    base = f"/api/v1/legacy-paper-imports/accounts/{_SOURCE_ACCOUNT_ID}"
    try:
        refused = await client.post(f"{base}/migrate", json={"confirmed": True})
        assert refused.status_code == 409
        assert refused.json()["details"]["code"] == "LEGACY_EQUITY_RESIDUAL_UNREPRESENTABLE"

        frozen = await client.get(base)
        assert frozen.status_code == 200
        receipt = frozen.json()["source_receipt"]
        assert receipt is not None and receipt["state"] == "PREPARED"
        assert receipt["unallocated_equity_residual"] == "0.5"
        assert frozen.json()["target"]["source_receipt"] is None

        aborted = await client.post(
            f"{base}/rollback",
            json={
                "confirmed": True,
                "source_inventory_sha256": receipt["source_inventory_sha256"],
            },
        )
        assert aborted.status_code == 200, aborted.text
        assert aborted.json()["receipt"]["state"] == "ABORTED"
        async with legacy_paper_writer_lease(_SOURCE_ACCOUNT_ID):
            async with database.async_session_maker() as session:
                async with session.begin():
                    await session.execute(
                        update(Account)
                        .where(Account.id == _SOURCE_ACCOUNT_ID)
                        .values(current_cash=Account.current_cash)
                    )
    finally:
        configure_service_read(None)
        target_store.close()


def _http_user(subject: str) -> Any:
    from app.schemas.auth import TokenPayload

    return TokenPayload(sub=subject, username="afi12-http-import-owner")


def _http_import_directory(
    worker: _TargetWorker, scope: ExecutionScope, domain: PaperOwnerDomainV1
) -> ServiceReadAccessDirectory:
    paper_wire_scope = WireScope(
        _DOMAIN_REF,
        account_ref=_ACCOUNT_REF,
        strategy_ref=_STRATEGY_REF,
    )
    paper_binding = PaperSubmitBinding(
        control_mode="execution_only",
        mount="application.orders",
        scope_ref="afi12-http-import-owner-scope-v1",
        query_scope_ref="afi12-http-import-query-scope-v1",
        legacy_account_id=_SOURCE_ACCOUNT_ID,
        account_ref=_ACCOUNT_REF,
        execution_domain_ref=_DOMAIN_REF,
        strategy_ref=_STRATEGY_REF,
        paper_owner_domain=domain,
        wire_scope=paper_wire_scope,
        execution_scope=scope,
    )
    import_binding = PaperLegacyImportBinding(
        mount="application.paper_legacy_import",
        owner_subject=_SOURCE_OWNER_ID,
        legacy_account_id=_SOURCE_ACCOUNT_ID,
        scope_ref=paper_binding.scope_ref,
        paper_binding=paper_binding,
        symbol_bindings=(LegacyPaperSymbolBindingV1(_LEGACY_SYMBOL, _INSTRUMENT),),
    )
    identity = WireIdentity(
        WireRole.APPLICATION_CLIENT,
        "afi12-http-import-principal",
        _SOURCE_OWNER_ID,
        "afi12-http-import-actor",
    )
    access = ReadAccess(
        worker=worker,
        allow_order_scope_refs=frozenset({paper_binding.query_scope_ref}),
        allow_paper_submit_account_ids=frozenset({_SOURCE_ACCOUNT_ID}),
        allow_paper_legacy_import_account_ids=frozenset({_SOURCE_ACCOUNT_ID}),
        paper_submit_bindings={_SOURCE_ACCOUNT_ID: paper_binding},
        paper_legacy_import_bindings={_SOURCE_ACCOUNT_ID: import_binding},
        application_identity=identity,
    )
    return ServiceReadAccessDirectory({_SOURCE_OWNER_ID: access})
