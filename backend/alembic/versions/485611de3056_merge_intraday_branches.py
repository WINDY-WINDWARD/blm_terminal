"""merge_intraday_branches

Revision ID: 485611de3056
Revises: add_ticker_intraday, add_intraday_indicators
Create Date: 2026-05-29 13:11:59.502097

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '485611de3056'
down_revision: Union[str, Sequence[str], None] = ('add_ticker_intraday', 'add_intraday_indicators')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
