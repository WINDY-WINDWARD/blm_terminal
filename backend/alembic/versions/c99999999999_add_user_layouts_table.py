"""add user_layouts table

Revision ID: c99999999999
Revises: 873fc541db28
Create Date: 2026-08-03 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "c99999999999"
down_revision: Union[str, Sequence[str], None] = "873fc541db28"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Get the database connection to check if table exists
    conn = op.get_bind()
    inspector = inspect(conn)
    
    table_exists = "user_layouts" in inspector.get_table_names()
    
    if not table_exists:
        # Fresh database: create table with deleted_at column
        op.create_table(
            "user_layouts",
            sa.Column("id", sa.Integer(), nullable=False, primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.String(length=64), nullable=False),
            sa.Column("active_panels", sa.JSON(), nullable=False),
            sa.Column("panel_count", sa.Integer(), nullable=False),
            sa.Column("merged_groups", sa.JSON(), nullable=False),
            sa.Column("saved_at", sa.BigInteger(), nullable=False),
            sa.Column("deleted_at", sa.BigInteger(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("user_id", "name", name="uq_user_layout_name"),
        )
        with op.batch_alter_table("user_layouts", schema=None) as batch_op:
            batch_op.create_index("ix_user_layouts_user_id", ["user_id"])
    else:
        # Existing database: ensure deleted_at column exists
        columns = [col["name"] for col in inspector.get_columns("user_layouts")]
        
        if "deleted_at" not in columns:
            # Add deleted_at column if it doesn't exist
            with op.batch_alter_table("user_layouts", schema=None) as batch_op:
                batch_op.add_column(sa.Column("deleted_at", sa.BigInteger(), nullable=True))

        index_names = {idx["name"] for idx in inspector.get_indexes("user_layouts")}
        if "ix_user_layouts_user_id" not in index_names:
            op.create_index("ix_user_layouts_user_id", "user_layouts", ["user_id"])


def downgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    
    if "user_layouts" in inspector.get_table_names():
        columns = [col["name"] for col in inspector.get_columns("user_layouts")]
        
        with op.batch_alter_table("user_layouts", schema=None) as batch_op:
            if "ix_user_layouts_user_id" in [idx["name"] for idx in inspector.get_indexes("user_layouts")]:
                batch_op.drop_index("ix_user_layouts_user_id")
            if "deleted_at" in columns:
                batch_op.drop_column("deleted_at")
        
        # Keep the table on downgrade because this migration also supports
        # databases where user_layouts predated this revision.
