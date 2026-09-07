"""add_unique_constraint_to_ticker_intraday

Revision ID: 6904a6732333
Revises: c99999999999
Create Date: 2026-09-08 00:11:31.123374

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6904a6732333'
down_revision: Union[str, Sequence[str], None] = 'c99999999999'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: add unique indexes for upsert conflict handling."""
    op.create_index(
        'uq_ticker_intraday_sym_ts_interval',
        'ticker_intraday',
        ['symbol', 'timestamp', 'interval'],
        unique=True,
    )
    op.create_index(
        'uq_ticker_symbol_date_series',
        'ticker_daily',
        ['symbol', 'date', 'series'],
        unique=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('uq_ticker_symbol_date_series', table_name='ticker_daily')
    op.drop_index('uq_ticker_intraday_sym_ts_interval', table_name='ticker_intraday')
