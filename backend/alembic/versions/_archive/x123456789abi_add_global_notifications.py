"""Add global_notifications table for market-wide stock alerts.

Creates a separate table for global scan alerts (all NSE stocks) that is
independent of watchlist notifications. No watchlist_id FK — alerts are
global and not tied to any specific watchlist.

Revision ID: x123456789abi
Revises: x123456789abh
Create Date: 2026-04-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "x123456789abi"
down_revision: Union[str, Sequence[str], None] = "x123456789abh"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "global_notifications",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("exchange", sa.String(16), nullable=False, server_default="NSE"),
        sa.Column("trigger_type", sa.String(32), nullable=False),
        sa.Column("message", sa.String(256), nullable=False),
        sa.Column("triggered_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("triggered_date", sa.Date(), nullable=False),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "symbol",
            "trigger_type",
            "triggered_date",
            name="uq_global_notification_daily",
        ),
    )
    op.create_index("ix_global_notifications_unread", "global_notifications", ["is_read"])
    op.create_index("ix_global_notifications_triggered_date", "global_notifications", ["triggered_date"])
    op.create_index("ix_global_notifications_symbol", "global_notifications", ["symbol"])


def downgrade() -> None:
    op.drop_index("ix_global_notifications_symbol", table_name="global_notifications")
    op.drop_index("ix_global_notifications_triggered_date", table_name="global_notifications")
    op.drop_index("ix_global_notifications_unread", table_name="global_notifications")
    op.drop_table("global_notifications")