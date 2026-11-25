"""add widget_tours table

Revision ID: a1234567890b
Revises: z11111111111a
Create Date: 2026-10-30 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "a1234567890b"
down_revision: Union[str, Sequence[str], None] = "z11111111111a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)

    table_exists = "widget_tours" in inspector.get_table_names()

    if not table_exists:
        op.create_table(
            "widget_tours",
            sa.Column("id", sa.Integer(), nullable=False, primary_key=True, autoincrement=True),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("widget_command", sa.String(length=32), nullable=False),
            sa.Column("seen_at", sa.BigInteger(), nullable=False),
            sa.UniqueConstraint("user_id", "widget_command", name="uq_widget_tour_user_command"),
        )
        with op.batch_alter_table("widget_tours", schema=None) as batch_op:
            batch_op.create_index("ix_widget_tours_user_id", ["user_id"])


def downgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    if "widget_tours" in inspector.get_table_names():
        op.drop_table("widget_tours")
