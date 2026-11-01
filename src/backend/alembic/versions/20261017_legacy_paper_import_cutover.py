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


_IMPORT_BINDING_COLUMNS = frozenset(
    {
        "source_kind",
        "source_import_receipt_id",
        "source_import_generation",
        "target_import_sha256",
    }
)


def _has_import_binding() -> bool:
    """Return whether a complete startup-created import binding already exists."""
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns(_RECEIPT)}
    if not _IMPORT_BINDING_COLUMNS.issubset(columns):
        return False
    checks = {check["name"] for check in inspector.get_check_constraints(_RECEIPT)}
    if not {
        "ck_legacy_paper_cutover_source_kind",
        "ck_legacy_paper_cutover_source_profile",
    }.issubset(checks):
        return False
    return any(
        foreign_key.get("constrained_columns") == ["source_import_receipt_id"]
        and foreign_key.get("referred_table") == _IMPORT_RECEIPT
        for foreign_key in inspector.get_foreign_keys(_RECEIPT)
    )


def _import_binding_foreign_key_name(bind) -> str | None:  # type: ignore[no-untyped-def]
    """Return the reflected FK name for the import binding when the dialect records one.

    MySQL refuses to drop a column that a foreign key still uses (error 1828).
    The migration names that FK ``fk_legacy_paper_cutover_import_receipt``, but a
    startup-created ORM schema carries the model's own constraint name, so the
    downgrade drops whatever name this schema actually reflects.  SQLite keeps no
    constraint names; its batch rebuild removes the FK together with the column.
    """
    for foreign_key in sa.inspect(bind).get_foreign_keys(_RECEIPT):
        if (
            foreign_key.get("constrained_columns") == ["source_import_receipt_id"]
            and foreign_key.get("referred_table") == _IMPORT_RECEIPT
        ):
            return foreign_key.get("name")
    return None


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
                predicate = (
                    "legacy_account_id = OLD.account_id OR legacy_account_id = NEW.account_id"
                )
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
    if _has_import_binding():
        # A startup-created current ORM schema already carries the import
        # binding and its named constraints.  Replaying the batch would try to
        # drop constraints the ORM schema never had.
        return
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns(_RECEIPT)}
    if columns & _IMPORT_BINDING_COLUMNS:
        raise RuntimeError("LEGACY_PAPER_IMPORT_CUTOVER_SCHEMA_CONFLICT")

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
        sa.text(f"SELECT count(*) FROM {_RECEIPT} WHERE source_kind = 'imported_legacy'")
    ).scalar_one()
    if imported_count:
        raise RuntimeError("cannot downgrade while imported cutover receipts exist")

    if bind.dialect.name == "sqlite":
        _drop_sqlite_writer_fence_triggers()
    import_binding_foreign_key = _import_binding_foreign_key_name(bind)
    with op.batch_alter_table(_RECEIPT) as batch_op:
        if import_binding_foreign_key is not None:
            batch_op.drop_constraint(import_binding_foreign_key, type_="foreignkey")
        batch_op.drop_constraint("ck_legacy_paper_cutover_source_profile", type_="check")
        batch_op.drop_constraint("ck_legacy_paper_cutover_source_kind", type_="check")
        batch_op.drop_column("target_import_sha256")
        batch_op.drop_column("source_import_generation")
        batch_op.drop_column("source_import_receipt_id")
        batch_op.drop_column("source_kind")
        batch_op.create_check_constraint("ck_legacy_paper_cutover_version", "receipt_version = 1")
        batch_op.create_check_constraint(
            "ck_legacy_paper_cutover_orders_empty", "source_order_count = 0"
        )
        batch_op.create_check_constraint(
            "ck_legacy_paper_cutover_positions_empty", "source_position_count = 0"
        )
        batch_op.create_check_constraint(
            "ck_legacy_paper_cutover_trades_empty", "source_trade_count = 0"
        )
    _restore_sqlite_writer_fence_triggers()
