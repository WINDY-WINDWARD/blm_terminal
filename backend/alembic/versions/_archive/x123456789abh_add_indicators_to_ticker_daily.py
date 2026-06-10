"""Add technical indicator columns to ticker_daily; drop ticker_indicators.

Adds 17 nullable indicator columns (RSI, MACD, Bollinger Bands, ATR, VWMA,
Historical Volatility, Sharpe Ratio, and a timestamp) directly to the
ticker_daily table so each OHLCV candle row also carries its computed
indicators.  The old single-row-per-symbol ticker_indicators table is dropped
as it is now redundant.

Revision ID: x123456789abh
Revises: x123456789abg
Create Date: 2026-04-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "x123456789abh"
down_revision: Union[str, Sequence[str], None] = "x123456789abg"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Notification threshold defaults seeded into system_config
_NOTIF_DEFAULTS: list[tuple[str, str]] = [
    ("notif.rsi_oversold_threshold",    "30"),
    ("notif.rsi_overbought_threshold",  "70"),
    ("notif.atr_expansion_threshold",   "4.0"),
    ("notif.return_1w_spike_threshold", "10.0"),
    ("notif.streak_days_threshold",     "5"),
    ("notif.near_52w_threshold",        "3.0"),
    ("notif.momentum_surge_threshold",  "70.0"),
    ("notif.volatility_spike_ratio",    "1.5"),
]


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Add indicator columns to ticker_daily (all nullable)
    # ------------------------------------------------------------------
    with op.batch_alter_table("ticker_daily") as batch_op:
        batch_op.add_column(sa.Column("rsi_14",               sa.Float(),    nullable=True))
        batch_op.add_column(sa.Column("macd",                 sa.Float(),    nullable=True))
        batch_op.add_column(sa.Column("macd_signal",          sa.Float(),    nullable=True))
        batch_op.add_column(sa.Column("macd_histogram",       sa.Float(),    nullable=True))
        batch_op.add_column(sa.Column("bb_middle",            sa.Float(),    nullable=True))
        batch_op.add_column(sa.Column("bb_upper",             sa.Float(),    nullable=True))
        batch_op.add_column(sa.Column("bb_lower",             sa.Float(),    nullable=True))
        batch_op.add_column(sa.Column("bb_width",             sa.Float(),    nullable=True))
        batch_op.add_column(sa.Column("bb_squeeze",           sa.String(1),  nullable=True))
        batch_op.add_column(sa.Column("atr_14",               sa.Float(),    nullable=True))
        batch_op.add_column(sa.Column("atr_percent",          sa.Float(),    nullable=True))
        batch_op.add_column(sa.Column("vwma_20",              sa.Float(),    nullable=True))
        batch_op.add_column(sa.Column("hv_20",                sa.Float(),    nullable=True))
        batch_op.add_column(sa.Column("hv_60",                sa.Float(),    nullable=True))
        batch_op.add_column(sa.Column("sharpe_60",            sa.Float(),    nullable=True))
        batch_op.add_column(sa.Column("sharpe_126",           sa.Float(),    nullable=True))
        batch_op.add_column(sa.Column("indicators_updated_at", sa.DateTime(), nullable=True))

    # ------------------------------------------------------------------
    # 2. Drop the old single-row-per-symbol ticker_indicators table
    # ------------------------------------------------------------------
    bind = op.get_bind()
    result = bind.execute(
        sa.text("SELECT name FROM sqlite_master WHERE type='table' AND name='ticker_indicators'")
    ).fetchone()
    if result:
        op.drop_table("ticker_indicators")

    # ------------------------------------------------------------------
    # 3. Seed notification threshold defaults into system_config
    #    (INSERT OR IGNORE so re-runs are idempotent)
    # ------------------------------------------------------------------
    from datetime import datetime
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    for key, value in _NOTIF_DEFAULTS:
        bind.execute(
            sa.text(
                "INSERT OR IGNORE INTO system_config (key, value, updated_at) "
                "VALUES (:key, :value, :ts)"
            ),
            {"key": key, "value": value, "ts": now_str},
        )


def downgrade() -> None:
    # Remove indicator columns from ticker_daily
    with op.batch_alter_table("ticker_daily") as batch_op:
        for col in (
            "rsi_14", "macd", "macd_signal", "macd_histogram",
            "bb_middle", "bb_upper", "bb_lower", "bb_width", "bb_squeeze",
            "atr_14", "atr_percent", "vwma_20",
            "hv_20", "hv_60", "sharpe_60", "sharpe_126",
            "indicators_updated_at",
        ):
            batch_op.drop_column(col)

    # Remove seeded system_config keys
    bind = op.get_bind()
    for key, _ in _NOTIF_DEFAULTS:
        bind.execute(sa.text("DELETE FROM system_config WHERE key = :key"), {"key": key})
