"""Add ticker_indicators table.

Revision ID: x123456789abg
Revises: x123456789abf
Create Date: 2026-04-13

"""
from alembic import op
import sqlalchemy as sa


revision = 'x123456789abg'
down_revision = 'x123456789abf'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'ticker_indicators',
        sa.Column('symbol', sa.String(32), primary_key=True),
        sa.Column('calculated_at', sa.DateTime(timezone=False), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('data_points', sa.Integer(), nullable=False),
        sa.Column('latest_date', sa.Date(), nullable=True),
        sa.Column('close', sa.Float(), nullable=True),
        sa.Column('rsi_14', sa.Float(), nullable=True),
        sa.Column('macd', sa.Float(), nullable=True),
        sa.Column('macd_signal', sa.Float(), nullable=True),
        sa.Column('macd_histogram', sa.Float(), nullable=True),
        sa.Column('bb_middle', sa.Float(), nullable=True),
        sa.Column('bb_upper', sa.Float(), nullable=True),
        sa.Column('bb_lower', sa.Float(), nullable=True),
        sa.Column('bb_width', sa.Float(), nullable=True),
        sa.Column('bb_squeeze', sa.String(1), nullable=True),
        sa.Column('atr_14', sa.Float(), nullable=True),
        sa.Column('atr_percent', sa.Float(), nullable=True),
        sa.Column('vwma_20', sa.Float(), nullable=True),
        sa.Column('hv_20', sa.Float(), nullable=True),
        sa.Column('hv_60', sa.Float(), nullable=True),
        sa.Column('sharpe_60', sa.Float(), nullable=True),
        sa.Column('sharpe_126', sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('ticker_indicators')