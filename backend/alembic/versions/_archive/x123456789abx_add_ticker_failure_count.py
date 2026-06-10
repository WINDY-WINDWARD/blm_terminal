"""add ticker_failure_count to stock_universe

Revision ID: x123456789abx
Revises: x123456789abk
Create Date: 2026-06-03 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "x123456789abx"
down_revision = "5a39988f6cb1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "stock_universe",
        sa.Column("ticker_failure_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("stock_universe", "ticker_failure_count")
