"""Join the additive analytics dataset and managed-paper migration branches.

Revision ID: 20261016_afi04_analytics_paper_merge
Revises: 20261016_portfolio_analytics_datasets_v1, 20261016_legacy_paper_cutover
Create Date: 2026-10-16
"""

from __future__ import annotations

revision = "20261016_afi04_analytics_paper_merge"
down_revision = (
    "20261016_portfolio_analytics_datasets_v1",
    "20261016_legacy_paper_cutover",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Join the two additive heads without changing application data."""


def downgrade() -> None:
    """Allow Alembic to move back to either branch's original head."""
