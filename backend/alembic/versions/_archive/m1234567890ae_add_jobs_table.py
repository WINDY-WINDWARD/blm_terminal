"""add_jobs_table

Revision ID: m1234567890ae
Revises: a1b2c3d4e5f7
Create Date: 2026-03-25 12:00:00.000000

Add jobs table for background task tracking.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "m1234567890ae"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=256), nullable=True),
        sa.Column("category", sa.String(length=32), nullable=True),
        sa.Column("schedule_type", sa.String(length=16), nullable=True),
        sa.Column("interval_seconds", sa.Integer(), nullable=True),
        sa.Column("cron_expression", sa.String(length=32), nullable=True),
        sa.Column("last_triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_trigger_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=512), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=True, server_default="idle"),
        sa.Column("progress_percent", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("progress_message", sa.String(length=128), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=True, server_default="1"),
        sa.Column("is_manual_only", sa.Boolean(), nullable=True, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_key", name="uq_jobs_job_key"),
    )
    op.create_index("ix_jobs_name", "jobs", ["name"])
    op.create_index("ix_jobs_status", "jobs", ["status"])
    op.create_index("ix_jobs_next_trigger_at", "jobs", ["next_trigger_at"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_jobs_next_trigger_at", table_name="jobs")
    op.drop_index("ix_jobs_status", table_name="jobs")
    op.drop_index("ix_jobs_name", table_name="jobs")
    op.drop_table("jobs")
