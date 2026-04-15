"""Add ticker_scores table for pre-computed multi-period returns and momentum.

Caches momentum scores and returns (1d, 1w, 1m, 3m, 6m, 1y) for all NSE symbols
computed once per day. Used by _global_scan_cycle() to re-enable momentum_surge
and return_1w_spike triggers without O(N²) DB queries.

Revision ID: x123456789abj
Revises: x123456789abi
Create Date: 2026-04-16
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "x123456789abj"
down_revision: Union[str, Sequence[str], None] = "x123456789abi"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ticker_scores",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("compute_date", sa.Date(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("return_1d", sa.Float(), nullable=True),
        sa.Column("return_1w", sa.Float(), nullable=True),
        sa.Column("return_1m", sa.Float(), nullable=True),
        sa.Column("return_3m", sa.Float(), nullable=True),
        sa.Column("return_6m", sa.Float(), nullable=True),
        sa.Column("return_1y", sa.Float(), nullable=True),
        sa.Column("momentum_score", sa.Float(), nullable=True),
        sa.Column("momentum_rank", sa.Integer(), nullable=True),
        sa.Column("universe_size", sa.Integer(), nullable=True),
        sa.Column("volume_ratio_20d", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol", name="uq_ticker_scores_symbol"),
    )
    op.create_index("ix_ticker_scores_compute_date", "ticker_scores", ["compute_date"])
    op.create_index("ix_ticker_scores_symbol", "ticker_scores", ["symbol"])


def downgrade() -> None:
    op.drop_index("ix_ticker_scores_symbol", table_name="ticker_scores")
    op.drop_index("ix_ticker_scores_compute_date", table_name="ticker_scores")
    op.drop_table("ticker_scores")