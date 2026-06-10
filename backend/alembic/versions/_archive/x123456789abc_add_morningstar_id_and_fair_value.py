"""add_morningstar_id_and_fair_value_to_stock_universe

Revision ID: x123456789abc
Revises: m1234567890ae
Create Date: 2026-03-25 20:30:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
import sqlalchemy.exc as sqla_exc

revision: str = "x123456789abc"
down_revision: Union[str, Sequence[str], None] = "m1234567890ae"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _add_column_if_not_exists(table_name: str, column: sa.Column) -> None:
    """Add a column only if it does not already exist (idempotent migration for SQLite)."""
    try:
        op.add_column(table_name, column)
    except sqla_exc.OperationalError as e:
        if "duplicate column name" in str(e).lower():
            pass
        else:
            raise


def upgrade() -> None:
    _add_column_if_not_exists(
        "stock_universe",
        sa.Column("morningstar_id", sa.String(32), nullable=True),
    )
    _add_column_if_not_exists(
        "stock_universe",
        sa.Column("fair_value", sa.Float, nullable=True),
    )
    _add_column_if_not_exists(
        "stock_universe",
        sa.Column("fair_value_updated_at", sa.DateTime(timezone=False), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("stock_universe", "fair_value_updated_at")
    op.drop_column("stock_universe", "fair_value")
    op.drop_column("stock_universe", "morningstar_id")