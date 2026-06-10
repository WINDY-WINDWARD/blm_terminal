"""last_update_time_nullable

Revision ID: b7c94d23e8a2
Revises: aaf83c15d9f1
Create Date: 2026-03-06 00:00:00.000000

Makes stock_universe.last_update_time nullable to handle NSE symbols
that return '-' as the lastUpdateTime (inactive/delisted equities).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "b7c94d23e8a2"
down_revision: Union[str, None] = "aaf83c15d9f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("stock_universe") as batch_op:
        batch_op.alter_column(
            "last_update_time",
            existing_type=sa.DateTime(),
            nullable=True,
        )


def downgrade() -> None:
    # NULL values must be backfilled before restoring NOT NULL.
    op.execute(
        "UPDATE stock_universe SET last_update_time = updated_at WHERE last_update_time IS NULL"
    )
    with op.batch_alter_table("stock_universe") as batch_op:
        batch_op.alter_column(
            "last_update_time",
            existing_type=sa.DateTime(),
            nullable=False,
        )
