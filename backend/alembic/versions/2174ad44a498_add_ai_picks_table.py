"""add ai_picks table

Revision ID: 2174ad44a498
Revises: x99999999999a
Create Date: 2026-06-12 04:54:30.528476

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2174ad44a498'
down_revision: Union[str, Sequence[str], None] = 'x99999999999a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('ai_picks',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('symbol', sa.String(), nullable=False),
    sa.Column('exchange', sa.String(), nullable=False),
    sa.Column('status', sa.Enum('NEW', 'ACTED_ON', 'CLOSED', 'ABANDONED', name='pickstatus'), nullable=False),
    sa.Column('direction', sa.Enum('LONG', 'SHORT', name='pickdirection'), nullable=False),
    sa.Column('entry_price', sa.Float(), nullable=False),
    sa.Column('take_profit', sa.Float(), nullable=False),
    sa.Column('stop_loss', sa.Float(), nullable=False),
    sa.Column('notes', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('status_updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('ai_picks', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_ai_picks_id'), ['id'], unique=False)
        batch_op.create_index(batch_op.f('ix_ai_picks_symbol'), ['symbol'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('ai_picks', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_ai_picks_symbol'))
        batch_op.drop_index(batch_op.f('ix_ai_picks_id'))

    op.drop_table('ai_picks')
