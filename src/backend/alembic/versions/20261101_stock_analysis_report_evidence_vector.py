"""Persist the revalidated OpenData stock-daily evidence vector on reports.

Revision ID: 20261101_stock_analysis_report_evidence_vector
Revises: 20261031_stock_daily_snapshot_grants
Create Date: 2026-11-01

# alembic-meta: estimated_rows=0; lock_kind=short

This nullable JSON column is default-off. Legacy reports keep ``NULL`` and
require no revalidation; a report that declares OpenData stock-daily
provenance may only be written after the adapter revalidated the pinned
publication and its grant receipt, and then persists the full vector here.
No existing column, constraint, index, or row is modified.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20261101_stock_analysis_report_evidence_vector"
down_revision = "20261031_stock_daily_snapshot_grants"
branch_labels = None
depends_on = None


def _report_columns() -> set[str]:
    """Return current report columns, tolerating a mid-chain/partial database."""
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("stock_analysis_reports"):
        return set()
    return {column["name"] for column in inspector.get_columns("stock_analysis_reports")}


def upgrade() -> None:
    # A create_all-first database may already have the ORM column. Never
    # duplicate it; skip only when the report table itself is absent from a
    # deliberately partial migration chain.
    columns = _report_columns()
    if not columns or "evidence_vector_json" in columns:
        return
    op.add_column(
        "stock_analysis_reports",
        sa.Column("evidence_vector_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    if "evidence_vector_json" not in _report_columns():
        return
    op.drop_column("stock_analysis_reports", "evidence_vector_json")
