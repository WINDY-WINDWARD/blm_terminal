"""add market category return 1d

Revision ID: z11111111111a
Revises: y11111111111a
Create Date: 2026-10-26 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'z11111111111a'
down_revision: Union[str, Sequence[str], None] = 'y11111111111a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    existing = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("market_categories")}
    with op.batch_alter_table('market_categories', schema=None) as batch_op:
        if 'return_1d' not in existing:
            batch_op.add_column(sa.Column('return_1d', sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('market_categories', schema=None) as batch_op:
        batch_op.drop_column('return_1d')
