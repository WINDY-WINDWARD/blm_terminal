"""merge heads abl and abm

Revision ID: 4cb23a53b80a
Revises: x123456789abl, x123456789abm
Create Date: 2026-05-19 00:32:44.877951

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4cb23a53b80a'
down_revision: Union[str, Sequence[str], None] = ('x123456789abl', 'x123456789abm')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
