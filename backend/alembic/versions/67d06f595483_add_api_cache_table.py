"""Add API cache table

Revision ID: 67d06f595483
Revises: e11111111111
Create Date: 2026-09-14 15:17:30.182244

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '67d06f595483'
down_revision: Union[str, Sequence[str], None] = 'e11111111111'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Handle the fact that we might have already created it from previous attempts
    op.execute("CREATE TABLE IF NOT EXISTS api_cache (key VARCHAR(255) NOT NULL, payload TEXT NOT NULL, created_at DATETIME NOT NULL, expires_at DATETIME NOT NULL, PRIMARY KEY (key))")
    op.execute("CREATE INDEX IF NOT EXISTS ix_api_cache_expires_at ON api_cache (expires_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_api_cache_key ON api_cache (key)")


def downgrade() -> None:
    op.drop_table('api_cache')
