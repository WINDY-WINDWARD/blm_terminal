"""add sync_state table for checkpointing

Revision ID: d99999999999
Revises: c99999999999
Create Date: 2026-09-10 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "d99999999999"
down_revision: Union[str, Sequence[str], None] = "6904a6732334"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)

    table_exists = "sync_state" in inspector.get_table_names()

    if not table_exists:
        op.create_table(
            "sync_state",
            sa.Column("task_name", sa.String(length=64), primary_key=True, nullable=False),
            sa.Column("last_symbol", sa.String(length=50), nullable=True),
            sa.Column("cursor_info", sa.String(length=256), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        )
        with op.batch_alter_table("sync_state", schema=None) as batch_op:
            batch_op.create_index("ix_sync_state_task_name", ["task_name"])


def downgrade() -> None:
    op.drop_table("sync_state")
