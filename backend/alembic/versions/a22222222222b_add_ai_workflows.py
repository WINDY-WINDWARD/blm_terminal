"""add ai_workflows, ai_workflow_runs, ai_custom_prompts tables

Revision ID: a22222222222b
Revises: a1234567890b
Create Date: 2026-10-31 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "a22222222222b"
down_revision: Union[str, Sequence[str], None] = "a1234567890b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    tables = inspector.get_table_names()

    if "ai_workflows" not in tables:
        op.create_table(
            "ai_workflows",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("description", sa.String(length=240), nullable=True),
            sa.Column("prompt", sa.Text(), nullable=False),
            sa.Column("schedule_type", sa.String(length=16), nullable=False, server_default="daily"),
            sa.Column("cron_expression", sa.String(length=64), nullable=False),
            sa.Column("timezone", sa.String(length=64), nullable=False, server_default="Asia/Kolkata"),
            sa.Column("time_of_day", sa.String(length=5), nullable=True),
            sa.Column("days_of_week", sa.String(length=32), nullable=True),
            sa.Column("once_at", sa.DateTime(timezone=False), nullable=True),
            sa.Column("symbols_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column(
                "watchlist_id",
                sa.Integer(),
                sa.ForeignKey("watchlists.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("model", sa.String(length=64), nullable=True),
            sa.Column("persona", sa.String(length=16), nullable=True),
            sa.Column("mode", sa.String(length=16), nullable=False, server_default="research"),
            sa.Column("allow_write_tools", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("catch_up_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("catch_up_window_hours", sa.Integer(), nullable=False, server_default="12"),
            sa.Column("next_run_at", sa.DateTime(timezone=False), nullable=True),
            sa.Column("last_run_at", sa.DateTime(timezone=False), nullable=True),
            sa.Column("last_success_at", sa.DateTime(timezone=False), nullable=True),
            sa.Column("last_slot_key", sa.String(length=80), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=False), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=False), server_default=sa.func.now(), nullable=False),
            sa.Column("deleted_at", sa.DateTime(timezone=False), nullable=True),
        )
        with op.batch_alter_table("ai_workflows", schema=None) as batch_op:
            batch_op.create_index("ix_ai_workflows_user_id", ["user_id"])
            batch_op.create_index(
                "ix_ai_workflows_user_enabled_next",
                ["user_id", "is_enabled", "next_run_at"],
            )

    if "ai_workflow_runs" not in tables:
        op.create_table(
            "ai_workflow_runs",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
            sa.Column(
                "workflow_id",
                sa.Integer(),
                sa.ForeignKey("ai_workflows.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("trigger", sa.String(length=16), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="queued"),
            sa.Column("skip_reason", sa.String(length=32), nullable=True),
            sa.Column("scheduled_for", sa.DateTime(timezone=False), nullable=False),
            sa.Column("slot_key", sa.String(length=80), nullable=False),
            sa.Column("prompt_snapshot", sa.Text(), nullable=True),
            sa.Column("name_snapshot", sa.String(length=120), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=False), nullable=True),
            sa.Column("finished_at", sa.DateTime(timezone=False), nullable=True),
            sa.Column("duration_ms", sa.Integer(), nullable=True),
            sa.Column(
                "session_id",
                sa.Integer(),
                sa.ForeignKey("chat_sessions.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("output_text", sa.Text(), nullable=True),
            sa.Column("output_summary", sa.String(length=512), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("is_silent", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=False), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("workflow_id", "slot_key", name="uq_ai_workflow_run_slot"),
        )
        with op.batch_alter_table("ai_workflow_runs", schema=None) as batch_op:
            batch_op.create_index("ix_ai_workflow_runs_workflow_id", ["workflow_id"])
            batch_op.create_index("ix_ai_workflow_runs_user_id", ["user_id"])
            batch_op.create_index(
                "ix_ai_workflow_runs_user_unread",
                ["user_id", "is_read", "created_at"],
            )
            batch_op.create_index(
                "ix_ai_workflow_runs_workflow_created",
                ["workflow_id", "created_at"],
            )

    if "ai_custom_prompts" not in tables:
        op.create_table(
            "ai_custom_prompts",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("title", sa.String(length=80), nullable=False),
            sa.Column("tag", sa.String(length=48), nullable=False),
            sa.Column("description", sa.String(length=240), nullable=True),
            sa.Column("prompt", sa.Text(), nullable=False),
            sa.Column("icon", sa.String(length=8), nullable=True),
            sa.Column("mode", sa.String(length=16), nullable=False, server_default="research"),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("use_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_used_at", sa.DateTime(timezone=False), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=False), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=False), server_default=sa.func.now(), nullable=False),
            sa.Column("deleted_at", sa.DateTime(timezone=False), nullable=True),
        )
        with op.batch_alter_table("ai_custom_prompts", schema=None) as batch_op:
            batch_op.create_index("ix_ai_custom_prompts_user_id", ["user_id"])
            batch_op.create_index(
                "ix_ai_custom_prompts_user_mode_order",
                ["user_id", "mode", "sort_order"],
            )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    tables = inspector.get_table_names()

    if "ai_workflow_runs" in tables:
        op.drop_table("ai_workflow_runs")
    if "ai_workflows" in tables:
        op.drop_table("ai_workflows")
    if "ai_custom_prompts" in tables:
        op.drop_table("ai_custom_prompts")
