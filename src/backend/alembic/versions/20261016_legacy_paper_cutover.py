"""Record empty-account managed-paper cutover and fence the legacy ledger."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20261016_legacy_paper_cutover"
down_revision = (
    "20260908_ai_research_approval_authority",
    "20260909_market_data_constraint_name_portability",
    "20261016_approved_target_http_operations",
)
branch_labels = None
depends_on = None

_RECEIPT = "legacy_paper_cutover_receipts"
_LEASE = "legacy_paper_writer_leases"
_TABLES = ("paper_trading_orders", "paper_trading_positions", "paper_trades")


def upgrade() -> None:
    op.create_table(
        _RECEIPT,
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("legacy_account_id", sa.String(length=36), nullable=False),
        sa.Column("owner_subject", sa.String(length=256), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("receipt_version", sa.Integer(), nullable=False),
        sa.Column("source_inventory_sha256", sa.String(length=64), nullable=False),
        sa.Column("binding_sha256", sa.String(length=64), nullable=False),
        sa.Column("paper_domain_sha256", sa.String(length=64), nullable=False),
        sa.Column("scope_ref", sa.String(length=128), nullable=False),
        sa.Column("account_ref", sa.String(length=128), nullable=False),
        sa.Column("execution_domain_ref", sa.String(length=128), nullable=False),
        sa.Column("strategy_ref", sa.String(length=128), nullable=False),
        sa.Column("initial_cash", sa.String(length=64), nullable=False),
        sa.Column("initial_fees", sa.String(length=64), nullable=False),
        sa.Column("fee_rate", sa.String(length=64), nullable=False),
        sa.Column("source_order_count", sa.Integer(), nullable=False),
        sa.Column("source_position_count", sa.Integer(), nullable=False),
        sa.Column("source_trade_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("state = 'ACTIVE'", name="ck_legacy_paper_cutover_active"),
        sa.CheckConstraint("receipt_version = 1", name="ck_legacy_paper_cutover_version"),
        sa.CheckConstraint("source_order_count = 0", name="ck_legacy_paper_cutover_orders_empty"),
        sa.CheckConstraint(
            "source_position_count = 0", name="ck_legacy_paper_cutover_positions_empty"
        ),
        sa.CheckConstraint("source_trade_count = 0", name="ck_legacy_paper_cutover_trades_empty"),
        sa.CheckConstraint(
            "length(source_inventory_sha256) = 64", name="ck_legacy_paper_cutover_inventory_hash"
        ),
        sa.CheckConstraint("length(binding_sha256) = 64", name="ck_legacy_paper_cutover_binding_hash"),
        sa.CheckConstraint(
            "length(paper_domain_sha256) = 64", name="ck_legacy_paper_cutover_domain_hash"
        ),
        sa.ForeignKeyConstraint(
            ["legacy_account_id"],
            ["paper_trading_accounts.id"],
            ondelete="RESTRICT",
            name="fk_legacy_paper_cutover_account",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("legacy_account_id", name="uq_legacy_paper_cutover_account"),
    )
    op.create_index(
        "ix_legacy_paper_cutover_owner", _RECEIPT, ["owner_subject"], unique=False
    )
    op.create_table(
        _LEASE,
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["paper_trading_accounts.id"],
            ondelete="CASCADE",
            name="fk_legacy_paper_writer_lease_account",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_legacy_paper_writer_leases_account", _LEASE, ["account_id"], unique=False
    )
    _install_writer_fence_triggers()


def _install_writer_fence_triggers() -> None:
    dialect = op.get_bind().dialect.name
    names = [
        "trg_lpc_receipt_no_update",
        "trg_lpc_receipt_no_delete",
        "trg_lpc_account_update",
        "trg_lpc_account_delete",
        *[f"trg_lpc_{table[-5:]}_{action.lower()}" for table in _TABLES for action in ("INSERT", "UPDATE", "DELETE")],
    ]
    if dialect == "sqlite":
        for name in names:
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS {name}"))
        op.execute(
            sa.text(
                f"CREATE TRIGGER trg_lpc_receipt_no_update BEFORE UPDATE ON {_RECEIPT} "
                "BEGIN SELECT RAISE(ABORT, 'LEGACY_PAPER_RECEIPT_IMMUTABLE'); END"
            )
        )
        op.execute(
            sa.text(
                f"CREATE TRIGGER trg_lpc_receipt_no_delete BEFORE DELETE ON {_RECEIPT} "
                "BEGIN SELECT RAISE(ABORT, 'LEGACY_PAPER_RECEIPT_IMMUTABLE'); END"
            )
        )
        op.execute(
            sa.text(
                "CREATE TRIGGER trg_lpc_account_update BEFORE UPDATE ON paper_trading_accounts "
                f"WHEN EXISTS (SELECT 1 FROM {_RECEIPT} WHERE legacy_account_id = OLD.id) "
                "BEGIN SELECT RAISE(ABORT, 'MANAGED_PAPER_LEGACY_ACCOUNT_FENCED'); END"
            )
        )
        op.execute(
            sa.text(
                "CREATE TRIGGER trg_lpc_account_delete BEFORE DELETE ON paper_trading_accounts "
                f"WHEN EXISTS (SELECT 1 FROM {_RECEIPT} WHERE legacy_account_id = OLD.id) "
                "BEGIN SELECT RAISE(ABORT, 'MANAGED_PAPER_LEGACY_ACCOUNT_FENCED'); END"
            )
        )
        for table in _TABLES:
            for action in ("INSERT", "UPDATE", "DELETE"):
                event = "OLD.account_id" if action == "DELETE" else "NEW.account_id"
                predicate = f"legacy_account_id = {event}"
                if action == "UPDATE":
                    predicate = (
                        "legacy_account_id = OLD.account_id OR "
                        "legacy_account_id = NEW.account_id"
                    )
                name = f"trg_lpc_{table[-5:]}_{action.lower()}"
                op.execute(
                    sa.text(
                        f"CREATE TRIGGER {name} BEFORE {action} ON {table} "
                        f"WHEN EXISTS (SELECT 1 FROM {_RECEIPT} WHERE {predicate}) "
                        "BEGIN SELECT RAISE(ABORT, 'MANAGED_PAPER_LEGACY_ACCOUNT_FENCED'); END"
                    )
                )
        return

    if dialect == "postgresql":
        op.execute(
            sa.text(
                """CREATE FUNCTION reject_legacy_paper_receipt_mutation() RETURNS trigger AS $$
                BEGIN
                    RAISE EXCEPTION 'LEGACY_PAPER_RECEIPT_IMMUTABLE';
                END;
                $$ LANGUAGE plpgsql"""
            )
        )
        op.execute(
            sa.text(
                "CREATE TRIGGER trg_lpc_receipt_no_update BEFORE UPDATE ON "
                f"{_RECEIPT} FOR EACH ROW EXECUTE FUNCTION reject_legacy_paper_receipt_mutation()"
            )
        )
        op.execute(
            sa.text(
                "CREATE TRIGGER trg_lpc_receipt_no_delete BEFORE DELETE ON "
                f"{_RECEIPT} FOR EACH ROW EXECUTE FUNCTION reject_legacy_paper_receipt_mutation()"
            )
        )
        op.execute(
            sa.text(
                """CREATE FUNCTION guard_legacy_paper_cutover_write() RETURNS trigger AS $$
                DECLARE account_key varchar(36);
                BEGIN
                    IF TG_TABLE_NAME = 'paper_trading_accounts' THEN
                        account_key := OLD.id;
                    ELSIF TG_OP = 'DELETE' THEN
                        account_key := OLD.account_id;
                    ELSIF TG_OP = 'UPDATE' THEN
                        IF OLD.account_id <> NEW.account_id THEN
                            RAISE EXCEPTION 'LEGACY_PAPER_ACCOUNT_MOVE_UNSUPPORTED';
                        END IF;
                        account_key := OLD.account_id;
                        PERFORM id FROM paper_trading_accounts
                         WHERE id = account_key ORDER BY id FOR UPDATE;
                        IF EXISTS (SELECT 1 FROM legacy_paper_cutover_receipts
                                   WHERE legacy_account_id = account_key) THEN
                            RAISE EXCEPTION 'MANAGED_PAPER_LEGACY_ACCOUNT_FENCED';
                        END IF;
                        RETURN NEW;
                    ELSE
                        account_key := NEW.account_id;
                    END IF;
                    IF TG_TABLE_NAME <> 'paper_trading_accounts' AND TG_OP <> 'UPDATE' THEN
                        PERFORM id FROM paper_trading_accounts
                         WHERE id = account_key ORDER BY id FOR UPDATE;
                    END IF;
                    IF EXISTS (SELECT 1 FROM legacy_paper_cutover_receipts
                               WHERE legacy_account_id = account_key) THEN
                        RAISE EXCEPTION 'MANAGED_PAPER_LEGACY_ACCOUNT_FENCED';
                    END IF;
                    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql"""
            )
        )
        for table, actions in (("paper_trading_accounts", "UPDATE OR DELETE"),) + tuple(
            (table, "INSERT OR UPDATE OR DELETE") for table in _TABLES
        ):
            op.execute(
                sa.text(
                    f"CREATE TRIGGER trg_lpc_{table[-5:]}_write_fence BEFORE {actions} ON {table} "
                    "FOR EACH ROW EXECUTE FUNCTION guard_legacy_paper_cutover_write()"
                )
            )
        return

    if dialect == "mysql":
        op.execute(
            sa.text(
                """CREATE TRIGGER trg_lpc_receipt_no_update BEFORE UPDATE ON legacy_paper_cutover_receipts
                FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'LEGACY_PAPER_RECEIPT_IMMUTABLE'"""
            )
        )
        op.execute(
            sa.text(
                """CREATE TRIGGER trg_lpc_receipt_no_delete BEFORE DELETE ON legacy_paper_cutover_receipts
                FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'LEGACY_PAPER_RECEIPT_IMMUTABLE'"""
            )
        )
        targets = [("paper_trading_accounts", "UPDATE", "OLD.id"), ("paper_trading_accounts", "DELETE", "OLD.id")]
        for table in _TABLES:
            targets.extend(
                [
                    (table, "INSERT", "NEW.account_id"),
                    (table, "UPDATE", "OLD.account_id"),
                    (table, "DELETE", "OLD.account_id"),
                ]
            )
        for table, action, account_expr in targets:
            name = f"trg_lpc_{table[-5:]}_{action.lower()}"
            predicate = f"legacy_account_id = {account_expr}"
            precheck = ""
            if table != "paper_trading_accounts":
                if action == "UPDATE":
                    precheck = (
                        "IF OLD.account_id <> NEW.account_id THEN "
                        "SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = "
                        "'LEGACY_PAPER_ACCOUNT_MOVE_UNSUPPORTED'; END IF; "
                    )
                precheck += (
                    "SELECT id INTO locked_account_id FROM paper_trading_accounts "
                    f"WHERE id = {account_expr} FOR UPDATE; "
                )
            op.execute(
                sa.text(
                    f"CREATE TRIGGER {name} BEFORE {action} ON {table} FOR EACH ROW "
                    f"BEGIN DECLARE locked_account_id VARCHAR(36); {precheck} "
                    f"IF EXISTS (SELECT 1 FROM {_RECEIPT} WHERE {predicate}) THEN "
                    "SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'MANAGED_PAPER_LEGACY_ACCOUNT_FENCED'; "
                    "END IF; END"
                )
            )
        return

    raise RuntimeError("LEGACY_PAPER_CUTOVER_UNSUPPORTED_DATABASE_DIALECT")


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        names = [
            "trg_lpc_receipt_no_update",
            "trg_lpc_receipt_no_delete",
            "trg_lpc_account_update",
            "trg_lpc_account_delete",
            *[f"trg_lpc_{table[-5:]}_{action.lower()}" for table in _TABLES for action in ("INSERT", "UPDATE", "DELETE")],
        ]
        for name in names:
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS {name}"))
    elif dialect == "postgresql":
        op.execute(sa.text(f"DROP TRIGGER IF EXISTS trg_lpc_receipt_no_update ON {_RECEIPT}"))
        op.execute(sa.text(f"DROP TRIGGER IF EXISTS trg_lpc_receipt_no_delete ON {_RECEIPT}"))
        for table in ("paper_trading_accounts", *_TABLES):
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS trg_lpc_{table[-5:]}_write_fence ON {table}"))
        op.execute(sa.text("DROP FUNCTION IF EXISTS guard_legacy_paper_cutover_write()"))
        op.execute(sa.text("DROP FUNCTION IF EXISTS reject_legacy_paper_receipt_mutation()"))
    elif dialect == "mysql":
        names = [
            "trg_lpc_receipt_no_update",
            "trg_lpc_receipt_no_delete",
            "trg_lpc_account_update",
            "trg_lpc_account_delete",
            *[f"trg_lpc_{table[-5:]}_{action.lower()}" for table in _TABLES for action in ("INSERT", "UPDATE", "DELETE")],
        ]
        for name in names:
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS {name}"))
    op.drop_index("ix_legacy_paper_writer_leases_account", table_name=_LEASE)
    op.drop_table(_LEASE)
    op.drop_index("ix_legacy_paper_cutover_owner", table_name=_RECEIPT)
    op.drop_table(_RECEIPT)
