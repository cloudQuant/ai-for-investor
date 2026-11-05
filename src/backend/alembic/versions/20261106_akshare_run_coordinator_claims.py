"""Create the AkShare run-coordinator control and claim tables.

Revision ID: 20261106_akshare_run_coordinator_claims
Revises: 20261101_stock_analysis_report_evidence_vector
Create Date: 2026-11-06

# alembic-meta: estimated_rows=0; lock_kind=short

``app/models/akshare_scheduler.py`` declares the durable claim/fence plane
behind ``AkshareRunCoordinator`` (iteration 204 AC13: single-writer plus lease
recovery). Both tables are new to the migration chain, so this revision only
creates them: no existing column, constraint, index or row is modified.

Development databases may already carry either table, because
``Base.metadata.create_all`` runs before Alembic stamping and the legacy plane
kept an ``ak_task_run_claims`` table with real rows. An existing table is
therefore accepted only when it matches the reviewed shape exactly; a partial
same-named table raises rather than being mistaken for a migrated one, and it
is never altered in place or silently re-created.

Downgrade treats both tables as coordination evidence: it drops them only while
they hold no rows, so a rollback can never erase issued fencing tokens or
completed business periods.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import context, op

revision = "20261106_akshare_run_coordinator_claims"
down_revision = "20261101_stock_analysis_report_evidence_vector"
branch_labels = None
depends_on = None

_CLAIMS_TABLE = "ak_task_run_claims"
_CONTROL_TABLE = "ak_scheduler_control"

# Lowercased type class name -> logical category. Covers both the types the ORM
# declares and the dialect-specific types an inspector reflects.
_TYPE_CATEGORY_ALIASES: dict[str, str] = {
    "bigint": "BigInteger",
    "bool": "Boolean",
    "boolean": "Boolean",
    "char": "String",
    "date": "Date",
    "datetime": "DateTime",
    "decimal": "Numeric",
    "double": "Float",
    "enum": "String",
    "float": "Float",
    "int": "Integer",
    "integer": "Integer",
    "json": "JSON",
    "largebinary": "LargeBinary",
    "mediumint": "Integer",
    "mediumtext": "Text",
    "nchar": "String",
    "numeric": "Numeric",
    "nvarchar": "String",
    "real": "Float",
    "smallint": "SmallInteger",
    "string": "String",
    "text": "Text",
    "time": "Time",
    "timestamp": "DateTime",
    "tinyint": "Integer",
    "tinytext": "Text",
    "unicode": "String",
    "uuid": "String",
    "varchar": "String",
}

# (column name -> (type, nullable)); derived directly from
# ``app/models/akshare_scheduler.py`` and kept in ORM declaration order.
_CLAIMS_COLUMNS: dict[str, tuple[sa.types.TypeEngine[object], bool]] = {
    "claim_key": (sa.String(length=64), False),
    "task_id": (sa.Integer(), True),
    "script_id": (sa.String(length=100), False),
    "source": (sa.String(length=50), False),
    "period_key": (sa.String(length=255), False),
    "parameter_hash": (sa.String(length=64), False),
    "parameters": (sa.JSON(), False),
    "status": (sa.String(length=20), False),
    "owner_id": (sa.String(length=64), True),
    "fencing_token": (sa.BigInteger(), False),
    "lease_expires_at": (sa.DateTime(), True),
    "attempt_count": (sa.Integer(), False),
    "next_retry_at": (sa.DateTime(), True),
    "execution_id": (sa.String(length=100), True),
    "last_error": (sa.Text(), True),
    "completed_at": (sa.DateTime(), True),
    "created_at": (sa.DateTime(), False),
    "updated_at": (sa.DateTime(), False),
}
_CLAIMS_PRIMARY_KEY = ("claim_key",)
# ``index=True`` on the ORM columns; names are SQLAlchemy's default
# ``ix_<table>_<column>`` so they match what ``create_all`` would emit.
_CLAIMS_INDEXES: tuple[tuple[str, str], ...] = (
    ("ix_ak_task_run_claims_task_id", "task_id"),
    ("ix_ak_task_run_claims_script_id", "script_id"),
    ("ix_ak_task_run_claims_source", "source"),
    ("ix_ak_task_run_claims_status", "status"),
    ("ix_ak_task_run_claims_lease_expires_at", "lease_expires_at"),
    ("ix_ak_task_run_claims_next_retry_at", "next_retry_at"),
    ("ix_ak_task_run_claims_execution_id", "execution_id"),
)

_CONTROL_COLUMNS: dict[str, tuple[sa.types.TypeEngine[object], bool]] = {
    "control_id": (sa.Integer(), False),
    "source_next_allowed_at": (sa.JSON(), False),
    "updated_at": (sa.DateTime(), False),
}
_CONTROL_PRIMARY_KEY = ("control_id",)


def _type_category(type_: sa.types.TypeEngine) -> str:
    """Reduce a declared or reflected type to one logical category.

    Dialects reflect their own subclasses with native names (``BIGINT`` for a
    ``BigInteger`` column, ``VARCHAR`` for ``String``), so both sides are mapped
    through the same alias table before comparison. This is the same reduction
    ``scripts/ci/check_orm_schema_drift.py`` applies, which keeps "the existing
    table matches the reviewed shape" meaning the same thing here and in CI.
    """
    name = type(type_).__name__.lower()
    return _TYPE_CATEGORY_ALIASES.get(name, type(type_).__name__)


def _require_absent_or_exact_table(
    bind: sa.Connection,
    table_name: str,
    expected_columns: dict[str, tuple[sa.types.TypeEngine[object], bool]],
    expected_primary_key: tuple[str, ...],
    expected_indexes: tuple[tuple[str, str], ...],
) -> bool:
    """Return whether a complete table already exists; create it when absent.

    A same-named table is only accepted when its columns, nullability, primary
    key and indexes match the reviewed shape exactly. Anything else is a real
    conflict with the legacy or partially created plane and must fail loudly
    rather than be silently upgraded in place or dropped.
    """
    inspector = sa.inspect(bind)
    if not inspector.has_table(table_name):
        return False

    observed_columns = {str(column["name"]): column for column in inspector.get_columns(table_name)}
    observed_index_names = {
        str(index["name"]) for index in inspector.get_indexes(table_name) if index.get("name")
    }
    observed_primary_key = tuple(
        str(column)
        for column in inspector.get_pk_constraint(table_name).get("constrained_columns") or ()
    )
    invalid_columns: dict[str, dict[str, object]] = {}
    for column_name, (expected_type, expected_nullable) in expected_columns.items():
        actual = observed_columns.get(column_name)
        if actual is None:
            continue
        actual_type = actual["type"]
        actual_nullable = bool(actual.get("nullable"))
        type_matches = _type_category(actual_type) == _type_category(expected_type)
        # String length is the only portable detail reflected on both engines.
        if isinstance(expected_type, sa.String) and isinstance(actual_type, sa.String):
            type_matches = type_matches and actual_type.length == expected_type.length
        if not type_matches or actual_nullable != expected_nullable:
            invalid_columns[column_name] = {
                "actual_type": _type_category(actual_type),
                "expected_type": _type_category(expected_type),
                "actual_nullable": actual_nullable,
                "expected_nullable": expected_nullable,
            }
    if (
        set(observed_columns) != set(expected_columns)
        or invalid_columns
        or observed_primary_key != expected_primary_key
        or observed_index_names != {name for name, _ in expected_indexes}
    ):
        details = {
            "table": table_name,
            "missing_columns": sorted(set(expected_columns) - set(observed_columns)),
            "unexpected_columns": sorted(set(observed_columns) - set(expected_columns)),
            "invalid_columns": invalid_columns,
            "primary_key": observed_primary_key,
            "expected_primary_key": expected_primary_key,
            "indexes": sorted(observed_index_names),
            "expected_indexes": sorted(name for name, _ in expected_indexes),
        }
        raise RuntimeError(f"AKSHARE_RUN_COORDINATOR_SCHEMA_CONFLICT: {details}")
    return True


def _create_table(
    table_name: str,
    expected_columns: dict[str, tuple[sa.types.TypeEngine[object], bool]],
    expected_primary_key: tuple[str, ...],
    expected_indexes: tuple[tuple[str, str], ...],
) -> None:
    op.create_table(
        table_name,
        *(
            sa.Column(column_name, type_, nullable=nullable)
            for column_name, (type_, nullable) in expected_columns.items()
        ),
        sa.PrimaryKeyConstraint(*expected_primary_key),
    )
    # `index-no-concurrently` (advisory): these indexes are built on the table this
    # same revision just created, so the table is empty and holds no in-flight
    # writers; `estimated_rows=0` above. `postgresql_concurrently=True` would also
    # require running the revision outside its transaction and is not used by any
    # other revision in this chain, which would make the SQLite/MySQL/PostgreSQL
    # paths diverge for no locking benefit on a brand-new table.
    for index_name, column_name in expected_indexes:
        op.create_index(index_name, table_name, [column_name], unique=False)


def upgrade() -> None:
    """Create the coordination tables; never rewrite a pre-existing one."""
    bind = op.get_bind()
    if not _require_absent_or_exact_table(
        bind, _CLAIMS_TABLE, _CLAIMS_COLUMNS, _CLAIMS_PRIMARY_KEY, _CLAIMS_INDEXES
    ):
        _create_table(_CLAIMS_TABLE, _CLAIMS_COLUMNS, _CLAIMS_PRIMARY_KEY, _CLAIMS_INDEXES)
    if not _require_absent_or_exact_table(
        bind, _CONTROL_TABLE, _CONTROL_COLUMNS, _CONTROL_PRIMARY_KEY, ()
    ):
        _create_table(_CONTROL_TABLE, _CONTROL_COLUMNS, _CONTROL_PRIMARY_KEY, ())


def _row_count(bind: sa.Connection, table_name: str) -> int:
    quoted = bind.dialect.identifier_preparer.quote(table_name)
    return int(bind.execute(sa.text(f"SELECT COUNT(*) FROM {quoted}")).scalar_one())


def downgrade() -> None:
    """Drop only unused coordination tables; never erase live claim evidence.

    ``ak_task_run_claims`` rows are durable idempotency records and
    ``ak_scheduler_control`` gates source rate limits; either table holding rows
    means the coordinator plane is in use, so rollback refuses rather than
    destroying issued fencing tokens and completed business periods.
    """
    if context.is_offline_mode():
        raise RuntimeError(
            "AKSHARE_RUN_COORDINATOR_DOWNGRADE_BLOCKED: "
            "offline SQL cannot prove the coordination tables are empty"
        )
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table_name, index_names in (
        (_CLAIMS_TABLE, tuple(name for name, _ in _CLAIMS_INDEXES)),
        (_CONTROL_TABLE, ()),
    ):
        if not inspector.has_table(table_name):
            continue
        rows = _row_count(bind, table_name)
        if rows:
            raise RuntimeError(
                f"AKSHARE_RUN_COORDINATOR_DOWNGRADE_BLOCKED: {table_name} still holds "
                f"{rows} row(s); drop the coordinator plane only after it is drained"
            )
        for index_name in index_names:
            op.drop_index(index_name, table_name=table_name)
        # `drop-table` (advisory): reached only after the row-count proof above, so
        # this drops an empty coordination table that nothing has claimed through yet.
        # A table that ever received a claim, lease or cooldown gate keeps its rows and
        # blocks the rollback instead; operators who want the data gone must archive
        # and drain it deliberately rather than let a `downgrade -1` erase fencing
        # history as a side effect.
        op.drop_table(table_name)
