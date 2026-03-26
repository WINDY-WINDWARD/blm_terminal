"""add_system_config_table

Revision ID: x123456789abd
Revises: x123456789abc
Create Date: 2026-03-26 14:58:00.000000

Add system_config table for tracking sync state.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "x123456789abd"
down_revision: Union[str, Sequence[str], None] = "x123456789abc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "system_config",
        sa.Column("key", sa.String(64), primary_key=True, index=True, nullable=False),
        sa.Column("value", sa.String(512), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("system_config")
