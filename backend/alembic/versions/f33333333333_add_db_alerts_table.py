"""Add db_alerts table (persisted DB-stats alert events)

Revision ID: f33333333333
Revises: f22222222222
Create Date: 2026-09-16 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = 'f33333333333'
down_revision: Union[str, Sequence[str], None] = 'f22222222222'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    existing_tables = set(inspect(conn).get_table_names())
    if "db_alerts" not in existing_tables:
        op.create_table(
            "db_alerts",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
            sa.Column("ts", sa.Float(), nullable=False),
            sa.Column("type", sa.String(length=64), nullable=False),
            sa.Column("severity", sa.String(length=16), nullable=False),
            sa.Column("message", sa.String(length=512), nullable=False),
            sa.Column("snapshot_json", sa.Text(), nullable=False, server_default="{}"),
        )
    # Plain CREATE INDEX (not batch mode — batch recreates reflected indexes
    # on SQLite and collides with the explicit create).
    op.execute("CREATE INDEX IF NOT EXISTS ix_db_alerts_ts ON db_alerts (ts)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_db_alerts_type ON db_alerts (type)")


def downgrade() -> None:
    conn = op.get_bind()
    existing_tables = set(inspect(conn).get_table_names())
    if "db_alerts" in existing_tables:
        op.drop_table("db_alerts")
