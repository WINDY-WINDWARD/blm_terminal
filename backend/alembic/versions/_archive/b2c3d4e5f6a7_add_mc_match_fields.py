"""add_mc_match_fields

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-03-16 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
import sqlalchemy.exc as sqla_exc

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _add_column_if_not_exists(table_name: str, column: sa.Column) -> None:
    """Add a column only if it does not already exist (idempotent migration for SQLite)."""
    try:
        op.add_column(table_name, column)
    except sqla_exc.OperationalError as e:
        if "duplicate column name" in str(e).lower():
            pass  # column already exists, safe to skip
        else:
            raise


def upgrade() -> None:
    _add_column_if_not_exists(
        "stock_universe",
        sa.Column("review_status", sa.String(32), nullable=True),
    )
    _add_column_if_not_exists(
        "stock_universe",
        sa.Column("match_confidence", sa.Float, nullable=True),
    )
    _add_column_if_not_exists(
        "stock_universe",
        sa.Column("mc_match_source", sa.String(32), nullable=True),
    )
    _add_column_if_not_exists(
        "stock_universe",
        sa.Column("mc_company_name", sa.String(255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("stock_universe", "mc_company_name")
    op.drop_column("stock_universe", "mc_match_source")
    op.drop_column("stock_universe", "match_confidence")
    op.drop_column("stock_universe", "review_status")
