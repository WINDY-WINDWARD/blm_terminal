"""add_series_to_stock_universe

Revision ID: 470ce9fa8403
Revises: x123456789newsnlp
Create Date: 2026-05-27 16:40:54.431500

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '470ce9fa8403'
down_revision: Union[str, Sequence[str], None] = 'x123456789newsnlp'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add series column to stock_universe."""
    with op.batch_alter_table('stock_universe', schema=None) as batch_op:
        batch_op.add_column(sa.Column('series', sa.String(length=8), nullable=True))


def downgrade() -> None:
    """Drop series column from stock_universe."""
    with op.batch_alter_table('stock_universe', schema=None) as batch_op:
        batch_op.drop_column('series')