"""merge_main_and_intraday_branches

Revision ID: 5a39988f6cb1
Revises: 470ce9fa8403, d8e1ed7addfa
Create Date: 2026-05-30 02:39:52.307001

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5a39988f6cb1'
down_revision: Union[str, Sequence[str], None] = ('470ce9fa8403', 'd8e1ed7addfa')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
