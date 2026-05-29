"""Add indicator columns to ticker_intraday

Revision ID: add_intraday_indicators
Revises: add_ticker_intraday
Create Date: 2026-05-29
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "add_intraday_indicators"
down_revision = "470ce9fa8403"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- indicator columns ---
    op.add_column("ticker_intraday", sa.Column("rsi_14", sa.Float(), nullable=True))
    op.add_column("ticker_intraday", sa.Column("macd", sa.Float(), nullable=True))
    op.add_column("ticker_intraday", sa.Column("macd_signal", sa.Float(), nullable=True))
    op.add_column("ticker_intraday", sa.Column("macd_histogram", sa.Float(), nullable=True))
    op.add_column("ticker_intraday", sa.Column("bb_middle", sa.Float(), nullable=True))
    op.add_column("ticker_intraday", sa.Column("bb_upper", sa.Float(), nullable=True))
    op.add_column("ticker_intraday", sa.Column("bb_lower", sa.Float(), nullable=True))
    op.add_column("ticker_intraday", sa.Column("bb_width", sa.Float(), nullable=True))
    op.add_column("ticker_intraday", sa.Column("bb_squeeze", sa.String(1), nullable=True))
    op.add_column("ticker_intraday", sa.Column("atr_14", sa.Float(), nullable=True))
    op.add_column("ticker_intraday", sa.Column("atr_percent", sa.Float(), nullable=True))
    op.add_column("ticker_intraday", sa.Column("vwma_20", sa.Float(), nullable=True))
    op.add_column("ticker_intraday", sa.Column("hv_20", sa.Float(), nullable=True))
    op.add_column("ticker_intraday", sa.Column("hv_60", sa.Float(), nullable=True))
    op.add_column("ticker_intraday", sa.Column("sharpe_60", sa.Float(), nullable=True))
    op.add_column("ticker_intraday", sa.Column("sharpe_126", sa.Float(), nullable=True))
    op.add_column(
        "ticker_intraday",
        sa.Column("indicators_updated_at", sa.DateTime(timezone=False), nullable=True),
    )

    # --- index for stale-indicator queries ---
    op.create_index(
        "ix_ticker_intraday_sym_interval_ind_at",
        "ticker_intraday",
        ["symbol", "interval", "indicators_updated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_ticker_intraday_sym_interval_ind_at", table_name="ticker_intraday")
    op.drop_column("ticker_intraday", "indicators_updated_at")
    op.drop_column("ticker_intraday", "sharpe_126")
    op.drop_column("ticker_intraday", "sharpe_60")
    op.drop_column("ticker_intraday", "hv_60")
    op.drop_column("ticker_intraday", "hv_20")
    op.drop_column("ticker_intraday", "vwma_20")
    op.drop_column("ticker_intraday", "atr_percent")
    op.drop_column("ticker_intraday", "atr_14")
    op.drop_column("ticker_intraday", "bb_squeeze")
    op.drop_column("ticker_intraday", "bb_width")
    op.drop_column("ticker_intraday", "bb_lower")
    op.drop_column("ticker_intraday", "bb_upper")
    op.drop_column("ticker_intraday", "bb_middle")
    op.drop_column("ticker_intraday", "macd_histogram")
    op.drop_column("ticker_intraday", "macd_signal")
    op.drop_column("ticker_intraday", "macd")
    op.drop_column("ticker_intraday", "rsi_14")
