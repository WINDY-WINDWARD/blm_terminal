"""Add paper_trades and paper_trade_legs tables

Revision ID: e11111111111
Revises: d99999999999
Create Date: 2026-09-13 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "e11111111111"
down_revision: Union[str, Sequence[str], None] = "d99999999999"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    existing_tables = set(inspector.get_table_names())

    if "paper_trades" not in existing_tables:
        op.create_table(
            "paper_trades",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
            sa.Column("symbol", sa.String(length=32), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="OPEN"),
            sa.Column("created_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        )
        with op.batch_alter_table("paper_trades", schema=None) as batch_op:
            batch_op.create_index("ix_paper_trades_symbol", ["symbol"], unique=False)
            batch_op.create_index("ix_paper_trades_status", ["status"], unique=False)

    if "paper_trade_legs" not in existing_tables:
        op.create_table(
            "paper_trade_legs",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
            sa.Column("paper_trade_id", sa.Integer(), sa.ForeignKey("paper_trades.id", ondelete="CASCADE"), nullable=False),
            sa.Column("action", sa.String(length=8), nullable=False),
            sa.Column("quantity", sa.Integer(), nullable=False),
            sa.Column("price", sa.Float(), nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        )
        with op.batch_alter_table("paper_trade_legs", schema=None) as batch_op:
            batch_op.create_index("ix_paper_trade_legs_paper_trade_id", ["paper_trade_id"], unique=False)


def downgrade() -> None:
    op.drop_table("paper_trade_legs")
    op.drop_table("paper_trades")
