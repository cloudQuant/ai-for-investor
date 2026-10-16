"""Freeze and hand off a non-empty legacy paper account without double ownership.

Revision ID: 20261016_legacy_paper_import
Revises: 20261016_afi04_analytics_paper_merge
Create Date: 2026-10-17
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "20261016_legacy_paper_import"
down_revision = "20261016_afi04_analytics_paper_merge"
branch_labels = None
depends_on = None

_RECEIPT = "legacy_paper_import_receipts"
_SOURCE_TABLES = ("paper_trading_orders", "paper_trading_positions", "paper_trades")


def _large_text_type():
    return sa.Text().with_variant(mysql.LONGTEXT(), "mysql")


def upgrade() -> None:
    op.create_table(
        _RECEIPT,
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("legacy_account_id", sa.String(length=36), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("active_fence_key", sa.String(length=36), nullable=True),
        sa.Column("owner_subject", sa.String(length=256), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("receipt_version", sa.Integer(), nullable=False),
        sa.Column("source_inventory_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_snapshot_json", _large_text_type(), nullable=False),
        sa.Column("target_import_sha256", sa.String(length=64), nullable=False),
        sa.Column("target_domain_sha256", sa.String(length=64), nullable=False),
        sa.Column("binding_sha256", sa.String(length=64), nullable=False),
        sa.Column("target_scope_key", sa.String(length=128), nullable=False),
        sa.Column("target_account_key", sa.String(length=128), nullable=False),
        sa.Column("cash_currency", sa.String(length=16), nullable=False),
        sa.Column("opening_cash", sa.String(length=64), nullable=False),
        sa.Column("cumulative_fees", sa.String(length=64), nullable=False),
        sa.Column("unallocated_equity_residual", sa.String(length=64), nullable=False),
        sa.Column("source_order_count", sa.Integer(), nullable=False),
        sa.Column("source_position_count", sa.Integer(), nullable=False),
        sa.Column("source_trade_count", sa.Integer(), nullable=False),
        sa.Column("preserved_context_sha256", sa.String(length=64), nullable=False),
        sa.Column("preserved_context_json", _large_text_type(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("generation > 0", name="ck_legacy_paper_import_generation_positive"),
        sa.CheckConstraint("receipt_version = 1", name="ck_legacy_paper_import_version"),
        sa.CheckConstraint(
            "state IN ('PREPARED', 'COMMITTED', 'ACTIVE', 'ABORTED')",
            name="ck_legacy_paper_import_state",
        ),
        sa.CheckConstraint("length(source_inventory_sha256) = 64", name="ck_legacy_paper_import_source_hash"),
        sa.CheckConstraint("length(target_import_sha256) = 64", name="ck_legacy_paper_import_target_hash"),
        sa.CheckConstraint("length(target_domain_sha256) = 64", name="ck_legacy_paper_import_domain_hash"),
        sa.CheckConstraint("length(binding_sha256) = 64", name="ck_legacy_paper_import_binding_hash"),
        sa.CheckConstraint("length(preserved_context_sha256) = 64", name="ck_legacy_paper_import_context_hash"),
        sa.CheckConstraint("source_order_count >= 0", name="ck_legacy_paper_import_order_count"),
        sa.CheckConstraint("source_position_count >= 0", name="ck_legacy_paper_import_position_count"),
        sa.CheckConstraint("source_trade_count >= 0", name="ck_legacy_paper_import_trade_count"),
        sa.ForeignKeyConstraint(
            ["legacy_account_id"],
            ["paper_trading_accounts.id"],
            ondelete="RESTRICT",
            name="fk_legacy_paper_import_account",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "legacy_account_id", "generation", name="uq_legacy_paper_import_generation"
        ),
        sa.UniqueConstraint("active_fence_key", name="uq_legacy_paper_import_active_fence"),
    )
    op.create_index("ix_legacy_paper_import_owner", _RECEIPT, ["owner_subject"])
    op.create_index("ix_legacy_paper_import_target_scope", _RECEIPT, ["target_scope_key"])
    _install_receipt_guards()
    _install_source_write_fence()


def _install_receipt_guards() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute(
            sa.text(
                f"CREATE TRIGGER trg_lpi_receipt_insert_guard BEFORE INSERT ON {_RECEIPT} "
                "WHEN NEW.state <> 'PREPARED' "
                "OR NEW.active_fence_key IS NOT NEW.legacy_account_id "
                "BEGIN SELECT RAISE(ABORT, 'LEGACY_PAPER_IMPORT_RECEIPT_INVALID'); END"
            )
        )
        op.execute(
            sa.text(
                f"CREATE TRIGGER trg_lpi_receipt_update_guard BEFORE UPDATE ON {_RECEIPT} "
                "WHEN NOT ("
                "NEW.id = OLD.id AND NEW.legacy_account_id = OLD.legacy_account_id "
                "AND NEW.generation = OLD.generation AND NEW.owner_subject = OLD.owner_subject "
                "AND NEW.receipt_version = OLD.receipt_version "
                "AND NEW.source_inventory_sha256 = OLD.source_inventory_sha256 "
                "AND NEW.source_snapshot_json = OLD.source_snapshot_json "
                "AND NEW.target_import_sha256 = OLD.target_import_sha256 "
                "AND NEW.target_domain_sha256 = OLD.target_domain_sha256 "
                "AND NEW.binding_sha256 = OLD.binding_sha256 "
                "AND NEW.target_scope_key = OLD.target_scope_key "
                "AND NEW.target_account_key = OLD.target_account_key "
                "AND NEW.cash_currency = OLD.cash_currency AND NEW.opening_cash = OLD.opening_cash "
                "AND NEW.cumulative_fees = OLD.cumulative_fees "
                "AND NEW.unallocated_equity_residual = OLD.unallocated_equity_residual "
                "AND NEW.source_order_count = OLD.source_order_count "
                "AND NEW.source_position_count = OLD.source_position_count "
                "AND NEW.source_trade_count = OLD.source_trade_count "
                "AND NEW.preserved_context_sha256 = OLD.preserved_context_sha256 "
                "AND NEW.preserved_context_json = OLD.preserved_context_json "
                "AND NEW.created_at = OLD.created_at AND NEW.updated_at > OLD.updated_at "
                "AND ((OLD.state = 'PREPARED' AND NEW.state IN ('COMMITTED', 'ABORTED')) "
                "OR (OLD.state = 'COMMITTED' AND NEW.state IN ('ACTIVE', 'ABORTED'))) "
                "AND ((NEW.state = 'ABORTED' AND NEW.active_fence_key IS NULL) "
                "OR (NEW.state <> 'ABORTED' AND NEW.active_fence_key IS NOT NULL "
                "AND NEW.active_fence_key = NEW.legacy_account_id))"
                ") BEGIN SELECT RAISE(ABORT, 'LEGACY_PAPER_IMPORT_RECEIPT_IMMUTABLE'); END"
            )
        )
        op.execute(
            sa.text(
                f"CREATE TRIGGER trg_lpi_receipt_delete_guard BEFORE DELETE ON {_RECEIPT} "
                "BEGIN SELECT RAISE(ABORT, 'LEGACY_PAPER_IMPORT_RECEIPT_IMMUTABLE'); END"
            )
        )
        return

    if dialect == "postgresql":
        op.execute(
            sa.text(
                """CREATE FUNCTION guard_legacy_paper_import_receipt() RETURNS trigger AS $$
                BEGIN
                    IF TG_OP = 'DELETE' THEN
                        RAISE EXCEPTION 'LEGACY_PAPER_IMPORT_RECEIPT_IMMUTABLE';
                    END IF;
                    IF TG_OP = 'INSERT' THEN
                        IF NEW.state <> 'PREPARED' OR NEW.active_fence_key IS DISTINCT FROM NEW.legacy_account_id THEN
                            RAISE EXCEPTION 'LEGACY_PAPER_IMPORT_RECEIPT_INVALID';
                        END IF;
                        RETURN NEW;
                    END IF;
                    IF NOT (
                        NEW.id = OLD.id AND NEW.legacy_account_id = OLD.legacy_account_id
                        AND NEW.generation = OLD.generation AND NEW.owner_subject = OLD.owner_subject
                        AND NEW.receipt_version = OLD.receipt_version
                        AND NEW.source_inventory_sha256 = OLD.source_inventory_sha256
                        AND NEW.source_snapshot_json = OLD.source_snapshot_json
                        AND NEW.target_import_sha256 = OLD.target_import_sha256
                        AND NEW.target_domain_sha256 = OLD.target_domain_sha256
                        AND NEW.binding_sha256 = OLD.binding_sha256
                        AND NEW.target_scope_key = OLD.target_scope_key
                        AND NEW.target_account_key = OLD.target_account_key
                        AND NEW.cash_currency = OLD.cash_currency AND NEW.opening_cash = OLD.opening_cash
                        AND NEW.cumulative_fees = OLD.cumulative_fees
                        AND NEW.unallocated_equity_residual = OLD.unallocated_equity_residual
                        AND NEW.source_order_count = OLD.source_order_count
                        AND NEW.source_position_count = OLD.source_position_count
                        AND NEW.source_trade_count = OLD.source_trade_count
                        AND NEW.preserved_context_sha256 = OLD.preserved_context_sha256
                        AND NEW.preserved_context_json = OLD.preserved_context_json
                        AND NEW.created_at = OLD.created_at AND NEW.updated_at > OLD.updated_at
                        AND ((OLD.state = 'PREPARED' AND NEW.state IN ('COMMITTED', 'ABORTED'))
                             OR (OLD.state = 'COMMITTED' AND NEW.state IN ('ACTIVE', 'ABORTED')))
                        AND ((NEW.state = 'ABORTED' AND NEW.active_fence_key IS NULL)
                             OR (NEW.state <> 'ABORTED' AND NEW.active_fence_key IS NOT NULL
                                 AND NEW.active_fence_key = NEW.legacy_account_id))
                    ) THEN
                        RAISE EXCEPTION 'LEGACY_PAPER_IMPORT_RECEIPT_IMMUTABLE';
                    END IF;
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql"""
            )
        )
        op.execute(
            sa.text(
                f"CREATE TRIGGER trg_lpi_receipt_guard BEFORE INSERT OR UPDATE OR DELETE ON {_RECEIPT} "
                "FOR EACH ROW EXECUTE FUNCTION guard_legacy_paper_import_receipt()"
            )
        )
        return

    if dialect == "mysql":
        op.execute(
            sa.text(
                f"""CREATE TRIGGER trg_lpi_receipt_insert_guard BEFORE INSERT ON {_RECEIPT}
                FOR EACH ROW BEGIN
                    IF NEW.state <> 'PREPARED' OR NOT (NEW.active_fence_key <=> NEW.legacy_account_id) THEN
                        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'LEGACY_PAPER_IMPORT_RECEIPT_INVALID';
                    END IF;
                END"""
            )
        )
        immutable_equal = (
            "NEW.id <=> OLD.id AND NEW.legacy_account_id <=> OLD.legacy_account_id "
            "AND NEW.generation = OLD.generation AND NEW.owner_subject = OLD.owner_subject "
            "AND NEW.receipt_version = OLD.receipt_version "
            "AND NEW.source_inventory_sha256 = OLD.source_inventory_sha256 "
            "AND NEW.source_snapshot_json = OLD.source_snapshot_json "
            "AND NEW.target_import_sha256 = OLD.target_import_sha256 "
            "AND NEW.target_domain_sha256 = OLD.target_domain_sha256 "
            "AND NEW.binding_sha256 = OLD.binding_sha256 AND NEW.target_scope_key = OLD.target_scope_key "
            "AND NEW.target_account_key = OLD.target_account_key AND NEW.cash_currency = OLD.cash_currency "
            "AND NEW.opening_cash = OLD.opening_cash AND NEW.cumulative_fees = OLD.cumulative_fees "
            "AND NEW.unallocated_equity_residual = OLD.unallocated_equity_residual "
            "AND NEW.source_order_count = OLD.source_order_count "
            "AND NEW.source_position_count = OLD.source_position_count "
            "AND NEW.source_trade_count = OLD.source_trade_count "
            "AND NEW.preserved_context_sha256 = OLD.preserved_context_sha256 "
            "AND NEW.preserved_context_json = OLD.preserved_context_json "
            "AND NEW.created_at = OLD.created_at AND NEW.updated_at > OLD.updated_at "
            "AND ((OLD.state = 'PREPARED' AND NEW.state IN ('COMMITTED', 'ABORTED')) "
            "OR (OLD.state = 'COMMITTED' AND NEW.state IN ('ACTIVE', 'ABORTED'))) "
            "AND ((NEW.state = 'ABORTED' AND NEW.active_fence_key IS NULL) "
            "OR (NEW.state <> 'ABORTED' AND NEW.active_fence_key <=> NEW.legacy_account_id)"
        )
        op.execute(
            sa.text(
                f"""CREATE TRIGGER trg_lpi_receipt_update_guard BEFORE UPDATE ON {_RECEIPT}
                FOR EACH ROW BEGIN
                    IF NOT ({immutable_equal}) THEN
                        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'LEGACY_PAPER_IMPORT_RECEIPT_IMMUTABLE';
                    END IF;
                END"""
            )
        )
        op.execute(
            sa.text(
                f"""CREATE TRIGGER trg_lpi_receipt_delete_guard BEFORE DELETE ON {_RECEIPT}
                FOR EACH ROW SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = 'LEGACY_PAPER_IMPORT_RECEIPT_IMMUTABLE'"""
            )
        )
        return

    raise RuntimeError("LEGACY_PAPER_IMPORT_UNSUPPORTED_DATABASE_DIALECT")


def _install_source_write_fence() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute(
            sa.text(
                "CREATE TRIGGER trg_lpi_account_update BEFORE UPDATE ON paper_trading_accounts "
                f"WHEN EXISTS (SELECT 1 FROM {_RECEIPT} WHERE active_fence_key = OLD.id) "
                "BEGIN SELECT RAISE(ABORT, 'MANAGED_PAPER_LEGACY_ACCOUNT_FENCED'); END"
            )
        )
        op.execute(
            sa.text(
                "CREATE TRIGGER trg_lpi_account_delete BEFORE DELETE ON paper_trading_accounts "
                f"WHEN EXISTS (SELECT 1 FROM {_RECEIPT} WHERE active_fence_key = OLD.id) "
                "BEGIN SELECT RAISE(ABORT, 'MANAGED_PAPER_LEGACY_ACCOUNT_FENCED'); END"
            )
        )
        for table in _SOURCE_TABLES:
            for action in ("INSERT", "UPDATE", "DELETE"):
                name = f"trg_lpi_{table}_{'ins' if action == 'INSERT' else 'upd' if action == 'UPDATE' else 'del'}"
                fence_predicate = (
                    "(active_fence_key = NEW.account_id)"
                    if action == "INSERT"
                    else "(active_fence_key = OLD.account_id)"
                    if action == "DELETE"
                    else "(active_fence_key = OLD.account_id OR active_fence_key = NEW.account_id)"
                )
                op.execute(
                    sa.text(
                        f"CREATE TRIGGER {name} BEFORE {action} ON {table} "
                        f"WHEN EXISTS (SELECT 1 FROM {_RECEIPT} WHERE {fence_predicate}) "
                        "BEGIN SELECT RAISE(ABORT, 'MANAGED_PAPER_LEGACY_ACCOUNT_FENCED'); END"
                    )
                )
        return

    if dialect == "postgresql":
        op.execute(
            sa.text(
                f"""CREATE FUNCTION guard_legacy_paper_import_source_write() RETURNS trigger AS $$
                DECLARE account_key varchar(36);
                BEGIN
                    IF TG_TABLE_NAME = 'paper_trading_accounts' THEN
                        account_key := OLD.id;
                    ELSIF TG_OP = 'DELETE' THEN
                        account_key := OLD.account_id;
                    ELSE
                        IF TG_OP = 'UPDATE' AND OLD.account_id <> NEW.account_id THEN
                            RAISE EXCEPTION 'LEGACY_PAPER_ACCOUNT_MOVE_UNSUPPORTED';
                        END IF;
                        account_key := NEW.account_id;
                    END IF;
                    IF TG_TABLE_NAME <> 'paper_trading_accounts' THEN
                        PERFORM id FROM paper_trading_accounts WHERE id = account_key FOR UPDATE;
                    END IF;
                    IF EXISTS (SELECT 1 FROM {_RECEIPT} WHERE active_fence_key = account_key) THEN
                        RAISE EXCEPTION 'MANAGED_PAPER_LEGACY_ACCOUNT_FENCED';
                    END IF;
                    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql"""
            )
        )
        for table, actions in (("paper_trading_accounts", "UPDATE OR DELETE"),) + tuple(
            (table, "INSERT OR UPDATE OR DELETE") for table in _SOURCE_TABLES
        ):
            op.execute(
                sa.text(
                    f"CREATE TRIGGER trg_lpi_{table}_write_fence BEFORE {actions} ON {table} "
                    "FOR EACH ROW EXECUTE FUNCTION guard_legacy_paper_import_source_write()"
                )
            )
        return

    if dialect == "mysql":
        targets = [("paper_trading_accounts", "UPDATE", "OLD.id"), ("paper_trading_accounts", "DELETE", "OLD.id")]
        for table in _SOURCE_TABLES:
            targets.extend(
                [
                    (table, "INSERT", "NEW.account_id"),
                    (table, "UPDATE", "OLD.account_id"),
                    (table, "DELETE", "OLD.account_id"),
                ]
            )
        for table, action, account_expr in targets:
            name = f"trg_lpi_{table}_{action.lower()}_fence"
            precheck = ""
            if table != "paper_trading_accounts":
                if action == "UPDATE":
                    precheck = (
                        "IF OLD.account_id <> NEW.account_id THEN SIGNAL SQLSTATE '45000' "
                        "SET MESSAGE_TEXT = 'LEGACY_PAPER_ACCOUNT_MOVE_UNSUPPORTED'; END IF; "
                    )
                precheck += (
                    "SELECT id INTO locked_account_id FROM paper_trading_accounts "
                    f"WHERE id = {account_expr} FOR UPDATE; "
                )
            op.execute(
                sa.text(
                    f"CREATE TRIGGER {name} BEFORE {action} ON {table} FOR EACH ROW "
                    f"BEGIN DECLARE locked_account_id VARCHAR(36); {precheck} "
                    f"IF EXISTS (SELECT 1 FROM {_RECEIPT} WHERE active_fence_key = {account_expr}) THEN "
                    "SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'MANAGED_PAPER_LEGACY_ACCOUNT_FENCED'; "
                    "END IF; END"
                )
            )
        return

    raise RuntimeError("LEGACY_PAPER_IMPORT_UNSUPPORTED_DATABASE_DIALECT")


def downgrade() -> None:
    active_import = op.get_bind().execute(
        sa.text(
            f"SELECT 1 FROM {_RECEIPT} "
            "WHERE state <> 'ABORTED' LIMIT 1"
        )
    ).first()
    if active_import is not None:
        raise RuntimeError("cannot remove the legacy paper import fence while an import is active")

    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        for table in ("paper_trading_accounts", *_SOURCE_TABLES):
            names = (
                ["trg_lpi_account_update", "trg_lpi_account_delete"]
                if table == "paper_trading_accounts"
                else [f"trg_lpi_{table}_{suffix}" for suffix in ("ins", "upd", "del")]
            )
            for name in names:
                op.execute(sa.text(f"DROP TRIGGER IF EXISTS {name}"))
        for name in (
            "trg_lpi_receipt_insert_guard",
            "trg_lpi_receipt_update_guard",
            "trg_lpi_receipt_delete_guard",
        ):
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS {name}"))
    elif dialect == "postgresql":
        for table in ("paper_trading_accounts", *_SOURCE_TABLES):
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS trg_lpi_{table}_write_fence ON {table}"))
        op.execute(sa.text(f"DROP TRIGGER IF EXISTS trg_lpi_receipt_guard ON {_RECEIPT}"))
        op.execute(sa.text("DROP FUNCTION IF EXISTS guard_legacy_paper_import_source_write()"))
        op.execute(sa.text("DROP FUNCTION IF EXISTS guard_legacy_paper_import_receipt()"))
    elif dialect == "mysql":
        names = [
            "trg_lpi_receipt_insert_guard",
            "trg_lpi_receipt_update_guard",
            "trg_lpi_receipt_delete_guard",
            "trg_lpi_paper_trading_accounts_update_fence",
            "trg_lpi_paper_trading_accounts_delete_fence",
        ]
        names.extend(
            f"trg_lpi_{table}_{action}_fence"
            for table in _SOURCE_TABLES
            for action in ("insert", "update", "delete")
        )
        for name in names:
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS {name}"))
    op.drop_index("ix_legacy_paper_import_target_scope", table_name=_RECEIPT)
    op.drop_index("ix_legacy_paper_import_owner", table_name=_RECEIPT)
    op.drop_table(_RECEIPT)
