"""merge two heads

Revision ID: 981b120a07df
Revises: b2c3d4e5f6a7, m1234567890ad
Create Date: 2026-03-18 13:33:13.050967

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '981b120a07df'
down_revision: Union[str, Sequence[str], None] = ('b2c3d4e5f6a7', 'm1234567890ad')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
