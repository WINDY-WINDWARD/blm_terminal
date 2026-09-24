"""Add Script Lab tables (saved_scripts, script_revisions, script_chart_state)

Revision ID: h66666666666
Revises: g55555555555
Create Date: 2026-09-24 00:00:00.000000

User chart scripts (BLM Script Lab v1, docs/specs/chart-scripts-v1.md):
immutable revisions + per-panel enablement/params. Follows the UserLayout
pattern (name-scoped, soft delete on the head row only).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'h66666666666'
down_revision: Union[str, Sequence[str], None] = 'g55555555555'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    tables = set(sa.inspect(conn).get_table_names())

    if "saved_scripts" not in tables:
        op.create_table(
            "saved_scripts",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.String(64), nullable=False),
            sa.Column("description", sa.String(280), nullable=False, server_default=""),
            sa.Column("is_builtin", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("head_rev_id", sa.Integer(), nullable=True),
            sa.Column("deleted_at", sa.BigInteger(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("user_id", "name", name="uq_saved_scripts_user_name"),
        )

    if "script_revisions" not in tables:
        op.create_table(
            "script_revisions",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("script_id", sa.Integer(), sa.ForeignKey("saved_scripts.id", ondelete="CASCADE"), nullable=False),
            sa.Column("rev_no", sa.Integer(), nullable=False),
            sa.Column("manifest", sa.JSON(), nullable=False),
            sa.Column("code", sa.Text(), nullable=False),
            sa.Column("note", sa.String(280), nullable=False, server_default=""),
            sa.Column("chat_session_id", sa.Integer(), sa.ForeignKey("chat_sessions.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("script_id", "rev_no", name="uq_script_revisions_script_rev"),
        )
        op.create_index("ix_script_revisions_script_id", "script_revisions", ["script_id"])

    if "script_chart_state" not in tables:
        op.create_table(
            "script_chart_state",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("panel_id", sa.String(64), nullable=False),
            sa.Column("script_id", sa.Integer(), sa.ForeignKey("saved_scripts.id", ondelete="CASCADE"), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("param_values", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("added_at", sa.BigInteger(), nullable=False),
            sa.UniqueConstraint("user_id", "panel_id", "script_id", name="uq_script_chart_state_slot"),
        )
        op.create_index("ix_script_chart_state_user_panel", "script_chart_state", ["user_id", "panel_id"])

    # Head-revision FK added after both tables exist (use_alter-style ordering).
    with op.batch_alter_table("saved_scripts") as batch:
        try:
            batch.create_foreign_key(
                "fk_saved_scripts_head_rev", "script_revisions",
                ["head_rev_id"], ["id"], ondelete="SET NULL",
            )
        except Exception:
            pass  # already present on re-run


def downgrade() -> None:
    conn = op.get_bind()
    tables = set(sa.inspect(conn).get_table_names())
    if "script_chart_state" in tables:
        op.drop_index("ix_script_chart_state_user_panel", table_name="script_chart_state")
        op.drop_table("script_chart_state")
    if "script_revisions" in tables:
        op.drop_index("ix_script_revisions_script_id", table_name="script_revisions")
        op.drop_table("script_revisions")
    if "saved_scripts" in tables:
        op.drop_table("saved_scripts")
