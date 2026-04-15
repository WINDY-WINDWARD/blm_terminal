"""Add 52-week high/low columns to stock_universe.

Revision ID: x123456789abf
Revises: x123456789abe
Create Date: 2026-04-13

"""
from alembic import op
import sqlalchemy as sa


revision = 'x123456789abf'
down_revision = 'x123456789abe'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'stock_universe',
        sa.Column('high_52w', sa.Float(), nullable=True),
    )
    op.add_column(
        'stock_universe',
        sa.Column('low_52w', sa.Float(), nullable=True),
    )
    op.add_column(
        'stock_universe',
        sa.Column('high_52w_date', sa.DateTime(timezone=False), nullable=True),
    )
    op.add_column(
        'stock_universe',
        sa.Column('low_52w_date', sa.DateTime(timezone=False), nullable=True),
    )
    op.add_column(
        'stock_universe',
        sa.Column('high_52w_updated_at', sa.DateTime(timezone=False), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('stock_universe', 'high_52w_updated_at')
    op.drop_column('stock_universe', 'low_52w_date')
    op.drop_column('stock_universe', 'high_52w_date')
    op.drop_column('stock_universe', 'low_52w')
    op.drop_column('stock_universe', 'high_52w')