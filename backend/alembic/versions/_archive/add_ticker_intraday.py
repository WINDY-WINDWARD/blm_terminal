"""Add ticker_intraday table for 1h/W/M candles from NSE charting API.

Revision ID: add_ticker_intraday
Revises: zzzzzzzzzzzz_seed_notif_system_config_defaults
Create Date: 2026-05-28
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "add_ticker_intraday"
down_revision = "x123456789abk"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ticker_intraday",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=False), nullable=False),
        sa.Column("interval", sa.String(4), nullable=False),
        sa.Column("open", sa.Float(), nullable=False),
        sa.Column("high", sa.Float(), nullable=False),
        sa.Column("low", sa.Float(), nullable=False),
        sa.Column("close", sa.Float(), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.String(32), nullable=False, server_default="nse_charting"),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.text("(CURRENT_TIMESTAMP)")),
        sa.UniqueConstraint("symbol", "timestamp", "interval", name="uq_ticker_intraday_sym_ts_interval"),
    )
    op.create_index("ix_ticker_intraday_symbol", "ticker_intraday", ["symbol"])
    op.create_index("ix_ticker_intraday_timestamp", "ticker_intraday", ["timestamp"])
    op.create_index("ix_ticker_intraday_symbol_interval", "ticker_intraday", ["symbol", "interval"])


def downgrade() -> None:
    op.drop_index("ix_ticker_intraday_symbol_interval", table_name="ticker_intraday")
    op.drop_index("ix_ticker_intraday_timestamp", table_name="ticker_intraday")
    op.drop_index("ix_ticker_intraday_symbol", table_name="ticker_intraday")
    op.drop_table("ticker_intraday")
