"""add_watchlists_table

Revision ID: m1234567890ad
Revises: m9876543210ab
Create Date: 2026-03-17 08:15:00.000000

Add watchlists table with foreign key to watchlist_items.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "m1234567890ad"
down_revision: Union[str, Sequence[str], None] = "m9876543210ab"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create watchlists table
    op.create_table(
        "watchlists",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # Add watchlist_id column to watchlist_items (nullable first, then set default)
    op.add_column(
        "watchlist_items",
        sa.Column(
            "watchlist_id",
            sa.Integer(),
            sa.ForeignKey("watchlists.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )

    # Create default watchlist
    op.execute("INSERT INTO watchlists (id, name) VALUES (1, 'Default')")

    # Set all existing items to belong to Default watchlist
    op.execute("UPDATE watchlist_items SET watchlist_id = 1 WHERE watchlist_id IS NULL")

    # Make watchlist_id not nullable
    op.alter_column(
        "watchlist_items",
        "watchlist_id",
        nullable=False,
    )

    # Update unique constraint to include watchlist_id
    op.drop_constraint("uq_watchlist_symbol_exchange", "watchlist_items", type_="unique")
    op.create_unique_constraint(
        "uq_watchlist_item",
        "watchlist_items",
        ["watchlist_id", "symbol", "exchange"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Drop unique constraint
    op.drop_constraint("uq_watchlist_item", "watchlist_items", type_="unique")
    op.create_unique_constraint(
        "uq_watchlist_symbol_exchange",
        "watchlist_items",
        ["symbol", "exchange"],
    )

    # Drop foreign key column
    op.drop_column("watchlist_items", "watchlist_id")

    # Drop watchlists table
    op.drop_table("watchlists")
