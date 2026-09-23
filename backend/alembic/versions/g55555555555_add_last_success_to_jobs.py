"""Add jobs.last_success_at (opportunistic catch-up signal)

Revision ID: g55555555555
Revises: f44444444444
Create Date: 2026-09-24 00:00:00.000000

Background daemons report "waiting"/"idle" every loop, and update_job_status
stamps last_completed_at on those transitions too — so last_completed_at
cannot tell "real work last completed" from "loop bookkeeping". The
missed-schedule catch-up needs the former: last_success_at is written only
on successful work completion (pipeline stages, triggered runs, daemon
syncs) and never by waiting/idle bookkeeping.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'g55555555555'
down_revision: Union[str, Sequence[str], None] = 'f44444444444'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    cols = {c["name"] for c in sa.inspect(conn).get_columns("jobs")}
    if "last_success_at" not in cols:
        op.add_column(
            "jobs",
            sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        )
    # Seed existing rows with "now": without this every pre-upgrade install
    # would look never-run and fire a full catch-up storm on first boot.
    # (Fresh installs get NULL rows from sync_job_to_db — correctly treated
    # as missed so day-one work actually happens.) The nightly-pipeline
    # >24h catch-up still fires independently when genuinely stale.
    conn.execute(
        sa.text("UPDATE jobs SET last_success_at = CURRENT_TIMESTAMP "
                "WHERE last_success_at IS NULL")
    )


def downgrade() -> None:
    conn = op.get_bind()
    cols = {c["name"] for c in sa.inspect(conn).get_columns("jobs")}
    if "last_success_at" in cols:
        op.drop_column("jobs", "last_success_at")
