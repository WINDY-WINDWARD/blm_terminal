"""Add ticker_screener_snapshot table for fast TQL screener lookups.

Denormalized one-row-per-symbol snapshot of every field the TQL screener
can filter on, including 1d/1h/W/M indicators, sector/industry/PE from
stock_universe, and 52-week high/low distance. Refreshed nightly +
post-bhavcopy by extending _ticker_scores_sync().

Replaces per-query window-function scan over ticker_daily/ticker_intraday
with a single SELECT against this small (~2.2K row) table joined to
ticker_scores for period returns.

Revision ID: x123456789abp
Revises: x123456789abx
Create Date: 2026-06-04
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "x123456789abp"
down_revision: Union[str, Sequence[str], None] = "x123456789abx"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ticker_screener_snapshot",
        sa.Column("symbol", sa.String(32), primary_key=True, nullable=False),
        sa.Column("last_date", sa.Date(), nullable=False),
        sa.Column("compute_date", sa.Date(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("last_close", sa.Float(), nullable=False),
        sa.Column("last_volume", sa.BigInteger(), nullable=False),
        sa.Column("last_open", sa.Float(), nullable=False),
        sa.Column("last_high", sa.Float(), nullable=False),
        sa.Column("last_low", sa.Float(), nullable=False),
        sa.Column("rsi_1d", sa.Float(), nullable=True),
        sa.Column("macd_1d", sa.Float(), nullable=True),
        sa.Column("macd_signal_1d", sa.Float(), nullable=True),
        sa.Column("macd_histogram_1d", sa.Float(), nullable=True),
        sa.Column("bb_middle_1d", sa.Float(), nullable=True),
        sa.Column("bb_upper_1d", sa.Float(), nullable=True),
        sa.Column("bb_lower_1d", sa.Float(), nullable=True),
        sa.Column("bb_width_1d", sa.Float(), nullable=True),
        sa.Column("bb_squeeze_1d", sa.String(1), nullable=True),
        sa.Column("atr_1d", sa.Float(), nullable=True),
        sa.Column("atr_percent_1d", sa.Float(), nullable=True),
        sa.Column("vwma_20_1d", sa.Float(), nullable=True),
        sa.Column("hv_20", sa.Float(), nullable=True),
        sa.Column("hv_60", sa.Float(), nullable=True),
        sa.Column("sharpe_60", sa.Float(), nullable=True),
        sa.Column("sharpe_126", sa.Float(), nullable=True),
        sa.Column("high_52w", sa.Float(), nullable=True),
        sa.Column("low_52w", sa.Float(), nullable=True),
        sa.Column("pct_from_52w_high", sa.Float(), nullable=True),
        sa.Column("pct_from_52w_low", sa.Float(), nullable=True),
        sa.Column("sector", sa.String(64), nullable=True),
        sa.Column("industry", sa.String(128), nullable=True),
        sa.Column("pe", sa.Float(), nullable=True),
        sa.Column("market_cap", sa.Float(), nullable=True),
        sa.Column("fair_value", sa.Float(), nullable=True),
        sa.Column("intraday_close_1h", sa.Float(), nullable=True),
        sa.Column("rsi_1h", sa.Float(), nullable=True),
        sa.Column("macd_1h", sa.Float(), nullable=True),
        sa.Column("macd_signal_1h", sa.Float(), nullable=True),
        sa.Column("macd_histogram_1h", sa.Float(), nullable=True),
        sa.Column("bb_middle_1h", sa.Float(), nullable=True),
        sa.Column("bb_upper_1h", sa.Float(), nullable=True),
        sa.Column("bb_lower_1h", sa.Float(), nullable=True),
        sa.Column("bb_width_1h", sa.Float(), nullable=True),
        sa.Column("bb_squeeze_1h", sa.String(1), nullable=True),
        sa.Column("atr_1h", sa.Float(), nullable=True),
        sa.Column("atr_percent_1h", sa.Float(), nullable=True),
        sa.Column("vwma_20_1h", sa.Float(), nullable=True),
        sa.Column("hv_20_1h", sa.Float(), nullable=True),
        sa.Column("hv_60_1h", sa.Float(), nullable=True),
        sa.Column("sharpe_60_1h", sa.Float(), nullable=True),
        sa.Column("sharpe_126_1h", sa.Float(), nullable=True),
        sa.Column("intraday_close_W", sa.Float(), nullable=True),
        sa.Column("rsi_W", sa.Float(), nullable=True),
        sa.Column("macd_W", sa.Float(), nullable=True),
        sa.Column("macd_signal_W", sa.Float(), nullable=True),
        sa.Column("macd_histogram_W", sa.Float(), nullable=True),
        sa.Column("bb_middle_W", sa.Float(), nullable=True),
        sa.Column("bb_upper_W", sa.Float(), nullable=True),
        sa.Column("bb_lower_W", sa.Float(), nullable=True),
        sa.Column("bb_width_W", sa.Float(), nullable=True),
        sa.Column("bb_squeeze_W", sa.String(1), nullable=True),
        sa.Column("atr_W", sa.Float(), nullable=True),
        sa.Column("atr_percent_W", sa.Float(), nullable=True),
        sa.Column("vwma_20_W", sa.Float(), nullable=True),
        sa.Column("hv_20_W", sa.Float(), nullable=True),
        sa.Column("hv_60_W", sa.Float(), nullable=True),
        sa.Column("sharpe_60_W", sa.Float(), nullable=True),
        sa.Column("sharpe_126_W", sa.Float(), nullable=True),
        sa.Column("intraday_close_M", sa.Float(), nullable=True),
        sa.Column("rsi_M", sa.Float(), nullable=True),
        sa.Column("macd_M", sa.Float(), nullable=True),
        sa.Column("macd_signal_M", sa.Float(), nullable=True),
        sa.Column("macd_histogram_M", sa.Float(), nullable=True),
        sa.Column("bb_middle_M", sa.Float(), nullable=True),
        sa.Column("bb_upper_M", sa.Float(), nullable=True),
        sa.Column("bb_lower_M", sa.Float(), nullable=True),
        sa.Column("bb_width_M", sa.Float(), nullable=True),
        sa.Column("bb_squeeze_M", sa.String(1), nullable=True),
        sa.Column("atr_M", sa.Float(), nullable=True),
        sa.Column("atr_percent_M", sa.Float(), nullable=True),
        sa.Column("vwma_20_M", sa.Float(), nullable=True),
        sa.Column("hv_20_M", sa.Float(), nullable=True),
        sa.Column("hv_60_M", sa.Float(), nullable=True),
        sa.Column("sharpe_60_M", sa.Float(), nullable=True),
        sa.Column("sharpe_126_M", sa.Float(), nullable=True),
    )
    op.create_index(
        "ix_snapshot_sector_pe", "ticker_screener_snapshot", ["sector", "pe"]
    )
    op.create_index(
        "ix_snapshot_compute_date", "ticker_screener_snapshot", ["compute_date"]
    )
    op.create_index(
        "ix_snapshot_last_date", "ticker_screener_snapshot", ["last_date"]
    )


def downgrade() -> None:
    op.drop_index("ix_snapshot_last_date", table_name="ticker_screener_snapshot")
    op.drop_index("ix_snapshot_compute_date", table_name="ticker_screener_snapshot")
    op.drop_index("ix_snapshot_sector_pe", table_name="ticker_screener_snapshot")
    op.drop_table("ticker_screener_snapshot")
