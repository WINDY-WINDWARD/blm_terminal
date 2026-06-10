"""add breakout_snapshots table

Revision ID: x99999999999a
Revises: x999999999999
Create Date: 2026-06-10 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'x99999999999a'
down_revision: Union[str, Sequence[str], None] = 'x999999999999'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'breakout_snapshots',
        sa.Column('id', sa.INTEGER, nullable=False, primary_key=True, autoincrement=True),
        sa.Column('snapshot_date', sa.DATE, nullable=False),
        sa.Column('breakout_type', sa.VARCHAR(16), nullable=False),
        sa.Column('symbol', sa.VARCHAR(32), nullable=False),
        sa.Column('ltp', sa.FLOAT, nullable=True),
        sa.Column('pchange', sa.FLOAT, nullable=True),
        sa.Column('extra_json', sa.TEXT, nullable=True),
        sa.UniqueConstraint('snapshot_date', 'breakout_type', 'symbol', name='uq_breakout_snapshot_daily'),
    )
    op.create_index('ix_breakout_snapshots_date', 'breakout_snapshots', ['snapshot_date'])
    op.create_index('ix_breakout_snapshots_symbol_type', 'breakout_snapshots', ['symbol', 'breakout_type'])


def downgrade() -> None:
    op.drop_index('ix_breakout_snapshots_symbol_type', table_name='breakout_snapshots')
    op.drop_index('ix_breakout_snapshots_date', table_name='breakout_snapshots')
    op.drop_table('breakout_snapshots')
