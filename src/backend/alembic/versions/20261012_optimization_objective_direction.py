"""Persist optimization objective metadata at task creation.

Revision ID: 20261012_optimization_objective_direction
Revises: 20260911_market_data_b2_completeness_evidence
Create Date: 2026-10-12
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# alembic-meta: estimated_rows=0; lock_kind=short
revision = "20261012_optimization_objective_direction"
down_revision = "20260911_market_data_b2_completeness_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("optimization_tasks"):
        raise RuntimeError(
            "OPTIMIZATION_OBJECTIVE_SCHEMA_CONFLICT: optimization_tasks table is missing"
        )

    columns = {column["name"]: column for column in inspector.get_columns("optimization_tasks")}
    expected_lengths = {"objective": 64, "direction": 16}
    for name, expected_length in expected_lengths.items():
        column = columns.get(name)
        if column is None:
            continue
        column_type = column["type"]
        if (
            not isinstance(column_type, sa.String)
            or column_type.length != expected_length
            or column["nullable"] is not True
        ):
            raise RuntimeError(
                "OPTIMIZATION_OBJECTIVE_SCHEMA_CONFLICT: "
                f"optimization_tasks.{name} must be nullable VARCHAR({expected_length})"
            )

    for name, expected_length in expected_lengths.items():
        if name not in columns:
            op.add_column(
                "optimization_tasks",
                sa.Column(name, sa.String(length=expected_length), nullable=True),
            )


def downgrade() -> None:
    op.drop_column("optimization_tasks", "direction")
    op.drop_column("optimization_tasks", "objective")
