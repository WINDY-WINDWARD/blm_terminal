"""add iinvest columns to stock_universe

Adds isin, iinvest_path, and iinvest_path_resolved_at columns to support
the iinvest.cogencis.com integration. These columns form the persistent
path cache for symbol→iinvest path resolution. No backfill required.

Revision ID: 31a1b2c3d4e5
Revises: 2174ad44a498
Create Date: 2026-06-18 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "31a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "2174ad44a498"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add iinvest lookup columns to stock_universe."""
    with op.batch_alter_table("stock_universe", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("isin", sa.String(length=12), nullable=True)
        )
        batch_op.add_column(
            sa.Column("iinvest_path", sa.String(length=256), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "iinvest_path_resolved_at",
                sa.DateTime(timezone=False),
                nullable=True,
            )
        )
        batch_op.create_index(
            batch_op.f("ix_stock_universe_isin"),
            ["isin"],
            unique=False,
        )


def downgrade() -> None:
    """Remove iinvest lookup columns from stock_universe."""
    with op.batch_alter_table("stock_universe", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_stock_universe_isin"))
        batch_op.drop_column("iinvest_path_resolved_at")
        batch_op.drop_column("iinvest_path")
        batch_op.drop_column("isin")
