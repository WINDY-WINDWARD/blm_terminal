"""Add job_executions table for background task execution history and live progress tracking.

Revision ID: i77777777777
Revises: h66666666666
Create Date: 2026-10-05 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'i77777777777'
down_revision: Union[str, Sequence[str], None] = 'h66666666666'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    tables = set(sa.inspect(conn).get_table_names())

    if "job_executions" not in tables:
        op.create_table(
            "job_executions",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("job_key", sa.String(64), nullable=False),
            sa.Column("name", sa.String(64), nullable=False),
            sa.Column("category", sa.String(32), nullable=True),
            sa.Column("triggered_by", sa.String(32), nullable=False, server_default="manual"),
            sa.Column("status", sa.String(32), nullable=False, server_default="running"),
            sa.Column("progress_percent", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("progress_message", sa.String(256), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("duration_seconds", sa.Float(), nullable=True),
            sa.Column("error", sa.String(1024), nullable=True),
            sa.Column("log_lines", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_job_executions_job_key", "job_executions", ["job_key"])
        op.create_index("ix_job_executions_status", "job_executions", ["status"])
        op.create_index("ix_job_executions_started_at", "job_executions", ["started_at"])


def downgrade() -> None:
    conn = op.get_bind()
    tables = set(sa.inspect(conn).get_table_names())
    if "job_executions" in tables:
        op.drop_index("ix_job_executions_started_at", table_name="job_executions")
        op.drop_index("ix_job_executions_status", table_name="job_executions")
        op.drop_index("ix_job_executions_job_key", table_name="job_executions")
        op.drop_table("job_executions")
