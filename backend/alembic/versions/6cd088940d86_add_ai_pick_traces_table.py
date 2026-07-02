"""Add ai_pick_traces table

Revision ID: 6cd088940d86
Revises: 31a1b2c3d4e6
Create Date: 2026-07-02 13:00:30.427662

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6cd088940d86'
down_revision: Union[str, Sequence[str], None] = '31a1b2c3d4e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('ai_pick_traces',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('pick_id', sa.Integer(), nullable=True),
    sa.Column('symbol', sa.String(), nullable=False),
    sa.Column('agent_role', sa.String(), nullable=False),
    sa.Column('prompt', sa.String(), nullable=False),
    sa.Column('response', sa.String(), nullable=False),
    sa.Column('duration_ms', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('error_message', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('ai_pick_traces', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_ai_pick_traces_id'), ['id'], unique=False)
        batch_op.create_index(batch_op.f('ix_ai_pick_traces_pick_id'), ['pick_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_ai_pick_traces_symbol'), ['symbol'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('ai_pick_traces', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_ai_pick_traces_symbol'))
        batch_op.drop_index(batch_op.f('ix_ai_pick_traces_pick_id'))
        batch_op.drop_index(batch_op.f('ix_ai_pick_traces_id'))
    op.drop_table('ai_pick_traces')
