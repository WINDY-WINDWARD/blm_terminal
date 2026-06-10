"""add_notifications_table

Revision ID: a1b2c3d4e5f7
Revises: 981b120a07df
Create Date: 2026-03-21 01:30:00.000000

Add notifications table for watchlist stock price alerts.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f7"
down_revision: Union[str, Sequence[str], None] = "981b120a07df"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "watchlist_id",
            sa.Integer(),
            sa.ForeignKey("watchlists.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("exchange", sa.String(length=16), nullable=True),
        sa.Column("trigger_type", sa.String(length=32), nullable=False),
        sa.Column("message", sa.String(length=256), nullable=False),
        sa.Column("triggered_at", sa.DateTime(), nullable=False),
        sa.Column("triggered_date", sa.Date(), nullable=False),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "watchlist_id",
            "symbol",
            "trigger_type",
            "triggered_date",
            name="uq_notification_daily",
        ),
    )
    op.create_index(
        "ix_notifications_watchlist_unread",
        "notifications",
        ["watchlist_id", "is_read"],
    )
    op.create_index(
        "ix_notifications_triggered_date",
        "notifications",
        ["triggered_date"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_notifications_triggered_date", table_name="notifications")
    op.drop_index("ix_notifications_watchlist_unread", table_name="notifications")
    op.drop_table("notifications")