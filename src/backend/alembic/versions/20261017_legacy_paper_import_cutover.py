"""Bind explicit managed cutover receipts to accepted legacy imports."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20261017_legacy_paper_import_cutover"
down_revision = "20261016_legacy_paper_import"
branch_labels = None
depends_on = None

_RECEIPT = "legacy_paper_cutover_receipts"
_IMPORT_RECEIPT = "legacy_paper_import_receipts"
_SOURCE_TABLES = ("paper_trading_orders", "paper_trading_positions", "paper_trades")
_SQLITE_FENCE_TRIGGERS = (
    "trg_lpc_receipt_no_update",
    "trg_lpc_receipt_no_delete",
    "trg_lpc_account_update",
    "trg_lpc_account_delete",
    *(
        f"trg_lpc_{table[-5:]}_{action.lower()}"
        for table in _SOURCE_TABLES
        for action in ("INSERT", "UPDATE", "DELETE")
    ),
)


def _source_profile_constraint() -> sa.CheckConstraint:
    return sa.CheckConstraint(
        "(source_kind = 'empty_account' AND receipt_version = 1 "
        "AND source_import_receipt_id IS NULL AND source_import_generation IS NULL "
        "AND target_import_sha256 IS NULL AND source_order_count = 0 "
        "AND source_position_count = 0 AND source_trade_count = 0) "
        "OR (source_kind = 'imported_legacy' AND receipt_version = 2 "
        "AND source_import_receipt_id IS NOT NULL "
        "AND source_import_generation IS NOT NULL AND source_import_generation > 0 "
        "AND target_import_sha256 IS NOT NULL AND length(target_import_sha256) = 64 "
        "AND source_order_count >= 0 AND source_position_count >= 0 "
        "AND source_trade_count >= 0 "
        "AND source_order_count + source_position_count + source_trade_count > 0)",
        name="ck_legacy_paper_cutover_source_profile",
    )


def _drop_sqlite_writer_fence_triggers() -> None:
    if op.get_bind().dialect.name != "sqlite":
        return
    for name in _SQLITE_FENCE_TRIGGERS:
        op.execute(sa.text(f"DROP TRIGGER IF EXISTS {name}"))


def _restore_sqlite_writer_fence_triggers() -> None:
    if op.get_bind().dialect.name != "sqlite":
        return
    op.execute(
        sa.text(
            f"CREATE TRIGGER trg_lpc_receipt_no_update BEFORE UPDATE ON {_RECEIPT} "
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
    for table in _SOURCE_TABLES:
        for action in ("INSERT", "UPDATE", "DELETE"):
            event = "OLD.account_id" if action == "DELETE" else "NEW.account_id"
            predicate = f"legacy_account_id = {event}"
            if action == "UPDATE":
                predicate = "legacy_account_id = OLD.account_id OR legacy_account_id = NEW.account_id"
            name = f"trg_lpc_{table[-5:]}_{action.lower()}"
            op.execute(
                sa.text(
                    f"CREATE TRIGGER {name} BEFORE {action} ON {table} "
                    f"WHEN EXISTS (SELECT 1 FROM {_RECEIPT} WHERE {predicate}) "
                    "BEGIN SELECT RAISE(ABORT, 'MANAGED_PAPER_LEGACY_ACCOUNT_FENCED'); END"
                )
            )
    op.execute(
        sa.text(
            f"CREATE TRIGGER trg_lpc_receipt_no_delete BEFORE DELETE ON {_RECEIPT} "
            "BEGIN SELECT RAISE(ABORT, 'LEGACY_PAPER_RECEIPT_IMMUTABLE'); END"
        )
    )


def upgrade() -> None:
    # SQLite batch rebuild drops/renames the receipt table while the existing
    # account and source-ledger triggers still refer to its old name.
    _drop_sqlite_writer_fence_triggers()
    with op.batch_alter_table(_RECEIPT) as batch_op:
        batch_op.add_column(
            sa.Column(
                "source_kind",
                sa.String(length=24),
                nullable=False,
                server_default=sa.text("'empty_account'"),
            )
        )
        batch_op.add_column(sa.Column("source_import_receipt_id", sa.String(length=36)))
        batch_op.add_column(sa.Column("source_import_generation", sa.Integer()))
        batch_op.add_column(sa.Column("target_import_sha256", sa.String(length=64)))
        batch_op.drop_constraint("ck_legacy_paper_cutover_version", type_="check")
        batch_op.drop_constraint("ck_legacy_paper_cutover_orders_empty", type_="check")
        batch_op.drop_constraint("ck_legacy_paper_cutover_positions_empty", type_="check")
        batch_op.drop_constraint("ck_legacy_paper_cutover_trades_empty", type_="check")
        batch_op.create_check_constraint(
            "ck_legacy_paper_cutover_source_kind",
            "source_kind IN ('empty_account', 'imported_legacy')",
        )
        batch_op.create_check_constraint(
            "ck_legacy_paper_cutover_source_profile",
            _source_profile_constraint().sqltext,
        )
        batch_op.create_foreign_key(
            "fk_legacy_paper_cutover_import_receipt",
            _IMPORT_RECEIPT,
            ["source_import_receipt_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    _restore_sqlite_writer_fence_triggers()


def downgrade() -> None:
    bind = op.get_bind()
    imported_count = bind.execute(
        sa.text(
            f"SELECT count(*) FROM {_RECEIPT} "
            "WHERE source_kind = 'imported_legacy'"
        )
    ).scalar_one()
    if imported_count:
        raise RuntimeError("cannot downgrade while imported cutover receipts exist")

    if bind.dialect.name == "sqlite":
        _drop_sqlite_writer_fence_triggers()
    with op.batch_alter_table(_RECEIPT) as batch_op:
        batch_op.drop_constraint("fk_legacy_paper_cutover_import_receipt", type_="foreignkey")
        batch_op.drop_constraint("ck_legacy_paper_cutover_source_profile", type_="check")
        batch_op.drop_constraint("ck_legacy_paper_cutover_source_kind", type_="check")
        batch_op.drop_column("target_import_sha256")
        batch_op.drop_column("source_import_generation")
        batch_op.drop_column("source_import_receipt_id")
        batch_op.drop_column("source_kind")
        batch_op.create_check_constraint("ck_legacy_paper_cutover_version", "receipt_version = 1")
        batch_op.create_check_constraint("ck_legacy_paper_cutover_orders_empty", "source_order_count = 0")
        batch_op.create_check_constraint(
            "ck_legacy_paper_cutover_positions_empty", "source_position_count = 0"
        )
        batch_op.create_check_constraint("ck_legacy_paper_cutover_trades_empty", "source_trade_count = 0")
    _restore_sqlite_writer_fence_triggers()
