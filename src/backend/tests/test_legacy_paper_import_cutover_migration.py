from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

_ACCOUNT_ID = "af130000-0000-4000-8000-000000000001"
_UNFENCED_ACCOUNT_ID = "af130000-0000-4000-8000-000000000002"
_OWNER_SUBJECT = "migration-owner@example.test"
_V1_RECEIPT_ID = "af130000-0000-4000-8000-000000000003"
_IMPORT_RECEIPT_ID = "af130000-0000-4000-8000-000000000004"
_V2_RECEIPT_ID = "af130000-0000-4000-8000-000000000005"
_HASH_A = "a" * 64
_HASH_B = "b" * 64
_HASH_C = "c" * 64

_SOURCE_TABLES = ("paper_trading_orders", "paper_trading_positions", "paper_trades")
_LPC_TRIGGERS = {
    "trg_lpc_receipt_no_update",
    "trg_lpc_receipt_no_delete",
    "trg_lpc_account_update",
    "trg_lpc_account_delete",
    *(f"trg_lpc_{table[-5:]}_{action}" for table in _SOURCE_TABLES for action in ("insert", "update", "delete")),
}
_V1_FIELDS = (
    "id",
    "legacy_account_id",
    "owner_subject",
    "state",
    "receipt_version",
    "source_inventory_sha256",
    "binding_sha256",
    "paper_domain_sha256",
    "scope_ref",
    "account_ref",
    "execution_domain_ref",
    "strategy_ref",
    "initial_cash",
    "initial_fees",
    "fee_rate",
    "source_order_count",
    "source_position_count",
    "source_trade_count",
    "created_at",
)


def _load_revision(name: str, filename: str) -> ModuleType:
    versions = Path(__file__).resolve().parents[1] / "alembic" / "versions"
    spec = importlib.util.spec_from_file_location(name, versions / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _apply_revision(connection: Connection, revision: ModuleType, action: str) -> None:
    context = MigrationContext.configure(connection)
    with Operations.context(context):
        getattr(revision, action)()


def _create_legacy_tables(connection: Connection) -> None:
    connection.exec_driver_sql(
        "CREATE TABLE paper_trading_accounts (id VARCHAR(36) PRIMARY KEY)"
    )
    for table in _SOURCE_TABLES:
        connection.exec_driver_sql(
            f"CREATE TABLE {table} (id VARCHAR(36) PRIMARY KEY, account_id VARCHAR(36) NOT NULL)"
        )
    connection.execute(
        sa.text("INSERT INTO paper_trading_accounts (id) VALUES (:id), (:other_id)"),
        {"id": _ACCOUNT_ID, "other_id": _UNFENCED_ACCOUNT_ID},
    )
    connection.execute(
        sa.text("INSERT INTO paper_trading_orders (id, account_id) VALUES ('legacy-order', :id)"),
        {"id": _UNFENCED_ACCOUNT_ID},
    )


def _v1_receipt_row() -> dict[str, Any]:
    return {
        "id": _V1_RECEIPT_ID,
        "legacy_account_id": _ACCOUNT_ID,
        "owner_subject": _OWNER_SUBJECT,
        "state": "ACTIVE",
        "receipt_version": 1,
        "source_inventory_sha256": _HASH_A,
        "binding_sha256": _HASH_B,
        "paper_domain_sha256": _HASH_C,
        "scope_ref": "legacy-paper-scope-v1",
        "account_ref": "simulation-account-v1",
        "execution_domain_ref": "paper-domain-v1",
        "strategy_ref": "strategy-v1",
        "initial_cash": "100.00",
        "initial_fees": "0.00",
        "fee_rate": "0.001",
        "source_order_count": 0,
        "source_position_count": 0,
        "source_trade_count": 0,
        "created_at": datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc),
    }


def _insert_v1_receipt(connection: Connection) -> dict[str, Any]:
    row = _v1_receipt_row()
    names = ", ".join(row)
    binds = ", ".join(f":{name}" for name in row)
    connection.execute(sa.text(f"INSERT INTO legacy_paper_cutover_receipts ({names}) VALUES ({binds})"), row)
    columns = ", ".join(_V1_FIELDS)
    persisted = connection.execute(
        sa.text(
            f"SELECT {columns} FROM legacy_paper_cutover_receipts WHERE id=:id"
        ),
        {"id": _V1_RECEIPT_ID},
    ).mappings().one()
    return dict(persisted)


def _seed_import_receipt(connection: Connection) -> None:
    created = "2026-10-17 12:00:00.000000"
    connection.execute(
        sa.text(
            """INSERT INTO legacy_paper_import_receipts (
                id, legacy_account_id, generation, active_fence_key, owner_subject, state,
                receipt_version, source_inventory_sha256, source_snapshot_json,
                target_import_sha256, target_domain_sha256, binding_sha256,
                target_scope_key, target_account_key, cash_currency, opening_cash,
                cumulative_fees, unallocated_equity_residual, source_order_count,
                source_position_count, source_trade_count, preserved_context_sha256,
                preserved_context_json, created_at, updated_at
            ) VALUES (
                :id, :account_id, 1, :account_id, :owner, 'PREPARED', 1,
                :source_hash, '{}', :target_hash, :domain_hash, :binding_hash,
                'target-scope-v1', 'target-account-v1', 'USDT', '89.9', '0.1',
                '0', 1, 0, 0, :context_hash, '{}', :created, :created
            )"""
        ),
        {
            "id": _IMPORT_RECEIPT_ID,
            "account_id": _ACCOUNT_ID,
            "owner": _OWNER_SUBJECT,
            "source_hash": _HASH_A,
            "target_hash": _HASH_B,
            "domain_hash": _HASH_C,
            "binding_hash": "d" * 64,
            "context_hash": "e" * 64,
            "created": created,
        },
    )
    connection.execute(
        sa.text(
            "UPDATE legacy_paper_import_receipts SET state='COMMITTED', "
            "updated_at='2026-10-17 12:00:01.000000' WHERE id=:id"
        ),
        {"id": _IMPORT_RECEIPT_ID},
    )
    connection.execute(
        sa.text(
            "UPDATE legacy_paper_import_receipts SET state='ACTIVE', "
            "updated_at='2026-10-17 12:00:02.000000' WHERE id=:id"
        ),
        {"id": _IMPORT_RECEIPT_ID},
    )


def _seed_v2_cutover_receipt(connection: Connection) -> None:
    connection.execute(
        sa.text(
            """INSERT INTO legacy_paper_cutover_receipts (
                id, legacy_account_id, owner_subject, state, receipt_version,
                source_inventory_sha256, binding_sha256, paper_domain_sha256,
                scope_ref, account_ref, execution_domain_ref, strategy_ref,
                initial_cash, initial_fees, fee_rate, source_order_count,
                source_position_count, source_trade_count, created_at, source_kind,
                source_import_receipt_id, source_import_generation, target_import_sha256
            ) VALUES (
                :id, :account_id, :owner, 'ACTIVE', 2, :source_hash, :binding_hash,
                :domain_hash, 'legacy-paper-scope-v1', 'simulation-account-v1',
                'paper-domain-v1', 'strategy-v1', '89.9', '0.1', '0.001',
                1, 0, 0, :created, 'imported_legacy', :import_id, 1, :target_hash
            )"""
        ),
        {
            "id": _V2_RECEIPT_ID,
            "account_id": _ACCOUNT_ID,
            "owner": _OWNER_SUBJECT,
            "source_hash": _HASH_A,
            "binding_hash": _HASH_B,
            "domain_hash": _HASH_C,
            "created": datetime(2026, 10, 17, 12, 1, tzinfo=timezone.utc),
            "import_id": _IMPORT_RECEIPT_ID,
            "target_hash": "f" * 64,
        },
    )


def _trigger_names(connection: Connection, *, prefix: str) -> set[str]:
    rows = connection.execute(
        sa.text("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE :prefix"),
        {"prefix": f"{prefix}%"},
    )
    return {row[0] for row in rows}


def _table_columns(connection: Connection, table: str) -> set[str]:
    return {row[1] for row in connection.exec_driver_sql(f"PRAGMA table_info({table})")}


def test_upgrade_preserves_existing_empty_v1_receipt_and_downgrade_restores_writer_fences() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    try:
        with engine.begin() as connection:
            _create_legacy_tables(connection)
            old_cutover = _load_revision(
                "paper_migration_test_old_cutover", "20261016_legacy_paper_cutover.py"
            )
            importer = _load_revision(
                "paper_migration_test_import", "20261016_legacy_paper_import.py"
            )
            new_cutover = _load_revision(
                "paper_migration_test_import_cutover", "20261017_legacy_paper_import_cutover.py"
            )
            _apply_revision(connection, old_cutover, "upgrade")
            original = _insert_v1_receipt(connection)
            assert _LPC_TRIGGERS == _trigger_names(connection, prefix="trg_lpc_")

            _apply_revision(connection, importer, "upgrade")
            # Keep an unrelated source row in place across both receipt-table rebuilds.
            source_before = connection.execute(
                sa.text("SELECT id, account_id FROM paper_trading_orders WHERE id='legacy-order'")
            ).one()
            _apply_revision(connection, new_cutover, "upgrade")

            migrated = connection.execute(
                sa.text("SELECT * FROM legacy_paper_cutover_receipts WHERE id=:id"),
                {"id": _V1_RECEIPT_ID},
            ).mappings().one()
            assert {field: migrated[field] for field in _V1_FIELDS} == original
            assert migrated["source_kind"] == "empty_account"
            assert migrated["source_import_receipt_id"] is None
            assert migrated["source_import_generation"] is None
            assert migrated["target_import_sha256"] is None
            assert _LPC_TRIGGERS == _trigger_names(connection, prefix="trg_lpc_")
            assert connection.execute(
                sa.text("SELECT id, account_id FROM paper_trading_orders WHERE id='legacy-order'")
            ).one() == source_before

            _apply_revision(connection, new_cutover, "downgrade")

            assert set(_V1_FIELDS) == _table_columns(connection, "legacy_paper_cutover_receipts")
            downgraded = connection.execute(
                sa.text("SELECT * FROM legacy_paper_cutover_receipts WHERE id=:id"),
                {"id": _V1_RECEIPT_ID},
            ).mappings().one()
            assert dict(downgraded) == original
            assert _LPC_TRIGGERS == _trigger_names(connection, prefix="trg_lpc_")
            with pytest.raises(IntegrityError):
                with connection.begin_nested():
                    connection.exec_driver_sql(
                        "UPDATE legacy_paper_cutover_receipts SET state='ACTIVE' "
                        f"WHERE id='{_V1_RECEIPT_ID}'"
                    )
            with pytest.raises(IntegrityError):
                with connection.begin_nested():
                    connection.exec_driver_sql(
                        f"DELETE FROM legacy_paper_cutover_receipts WHERE id='{_V1_RECEIPT_ID}'"
                    )
            with pytest.raises(IntegrityError):
                with connection.begin_nested():
                    connection.exec_driver_sql(
                        f"UPDATE paper_trading_accounts SET id=id WHERE id='{_ACCOUNT_ID}'"
                    )
            with pytest.raises(IntegrityError):
                with connection.begin_nested():
                    connection.exec_driver_sql(
                        "INSERT INTO paper_trading_orders (id, account_id) "
                        f"VALUES ('blocked-after-downgrade', '{_ACCOUNT_ID}')"
                    )
    finally:
        engine.dispose()


def test_downgrade_refuses_when_imported_v2_cutover_receipt_exists() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    try:
        with engine.begin() as connection:
            _create_legacy_tables(connection)
            old_cutover = _load_revision(
                "paper_import_v2_test_old_cutover", "20261016_legacy_paper_cutover.py"
            )
            importer = _load_revision(
                "paper_import_v2_test_import", "20261016_legacy_paper_import.py"
            )
            new_cutover = _load_revision(
                "paper_import_v2_test_import_cutover", "20261017_legacy_paper_import_cutover.py"
            )
            _apply_revision(connection, old_cutover, "upgrade")
            _apply_revision(connection, importer, "upgrade")
            _apply_revision(connection, new_cutover, "upgrade")
            _seed_import_receipt(connection)
            _seed_v2_cutover_receipt(connection)

            with pytest.raises(RuntimeError, match="cannot downgrade while imported cutover receipts exist"):
                _apply_revision(connection, new_cutover, "downgrade")

            assert "source_kind" in _table_columns(connection, "legacy_paper_cutover_receipts")
            receipt = connection.execute(
                sa.text("SELECT source_kind, receipt_version FROM legacy_paper_cutover_receipts WHERE id=:id"),
                {"id": _V2_RECEIPT_ID},
            ).one()
            assert receipt == ("imported_legacy", 2)
            assert _LPC_TRIGGERS == _trigger_names(connection, prefix="trg_lpc_")
            assert "trg_lpi_receipt_update_guard" in _trigger_names(
                connection, prefix="trg_lpi_"
            )
    finally:
        engine.dispose()
