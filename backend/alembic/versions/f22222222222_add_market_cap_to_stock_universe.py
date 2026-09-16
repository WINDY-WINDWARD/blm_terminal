"""Add market_cap_cr to stock_universe (NSE tradeInfo.totalMarketCap, Rs Cr)

Revision ID: f22222222222
Revises: 67d06f595483
Create Date: 2026-09-16 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = 'f22222222222'
down_revision: Union[str, Sequence[str], None] = '67d06f595483'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    cols = {c["name"] for c in inspect(conn).get_columns("stock_universe")}
    if "market_cap_cr" not in cols:
        op.add_column(
            "stock_universe",
            sa.Column("market_cap_cr", sa.Float(), nullable=True),
        )


def downgrade() -> None:
    conn = op.get_bind()
    cols = {c["name"] for c in inspect(conn).get_columns("stock_universe")}
    if "market_cap_cr" in cols:
        with op.batch_alter_table("stock_universe") as batch_op:
            batch_op.drop_column("market_cap_cr")
