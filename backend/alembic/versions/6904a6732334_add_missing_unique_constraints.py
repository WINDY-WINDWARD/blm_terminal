"""add_missing_unique_constraints

Revision ID: 6904a6732334
Revises: 6904a6732333
Create Date: 2026-09-10 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6904a6732334'
down_revision: Union[str, Sequence[str], None] = '6904a6732333'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: add missing unique indexes for ON CONFLICT upsert handling."""
    # 1. Unique index on ticker_scores(symbol)
    op.create_index(
        'uq_ticker_scores_symbol',
        'ticker_scores',
        ['symbol'],
        unique=True,
    )

    # 2. Unique index on notifications(watchlist_id, symbol, trigger_type, triggered_date)
    op.create_index(
        'uq_notification_daily',
        'notifications',
        ['watchlist_id', 'symbol', 'trigger_type', 'triggered_date'],
        unique=True,
    )

    # 3. Unique index on global_notifications(symbol, trigger_type, triggered_date)
    op.create_index(
        'uq_global_notification_daily',
        'global_notifications',
        ['symbol', 'trigger_type', 'triggered_date'],
        unique=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('uq_global_notification_daily', table_name='global_notifications')
    op.drop_index('uq_notification_daily', table_name='notifications')
    op.drop_index('uq_ticker_scores_symbol', table_name='ticker_scores')
