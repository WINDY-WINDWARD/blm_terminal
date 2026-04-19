"""add_ticker_daily_table

Revision ID: x123456789abe
Revises: x123456789abd
Create Date: 2026-04-10 15:00:00.000000

Add ticker_daily table for storing daily OHLCV data.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "x123456789abe"
down_revision: Union[str, Sequence[str], None] = "x123456789abd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    from sqlalchemy import text

    bind = op.get_bind()

    table_exists = bind.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='ticker_daily'")).fetchone()

    if not table_exists:
        op.create_table(
            "ticker_daily",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("symbol", sa.String(32), nullable=False),
            sa.Column("date", sa.Date, nullable=False),
            sa.Column("series", sa.String(4), nullable=False, server_default="EQ"),
            sa.Column("open", sa.Float, nullable=False),
            sa.Column("high", sa.Float, nullable=False),
            sa.Column("low", sa.Float, nullable=False),
            sa.Column("close", sa.Float, nullable=False),
            sa.Column("volume", sa.BigInteger, nullable=False),
            sa.Column("value", sa.Float, nullable=False),
            sa.Column("source", sa.String(32), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.UniqueConstraint("symbol", "date", "series", name="uq_ticker_symbol_date_series"),
        )

    def index_exists(name: str) -> bool:
        return bind.execute(text("SELECT name FROM sqlite_master WHERE type='index' AND name=:name"), {"name": name}).fetchone() is not None

    if not index_exists("ix_ticker_daily_symbol"):
        op.create_index("ix_ticker_daily_symbol", "ticker_daily", ["symbol"])
    if not index_exists("ix_ticker_daily_date"):
        op.create_index("ix_ticker_daily_date", "ticker_daily", ["date"])
    if not index_exists("ix_ticker_daily_symbol_date"):
        op.create_index("ix_ticker_daily_symbol_date", "ticker_daily", ["symbol", "date"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("ticker_daily")