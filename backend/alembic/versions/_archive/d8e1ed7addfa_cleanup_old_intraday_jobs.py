"""cleanup_old_intraday_jobs

Revision ID: d8e1ed7addfa
Revises: 485611de3056
Create Date: 2026-05-29 15:28:46.111726

"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision: str = 'd8e1ed7addfa'
down_revision: Union[str, Sequence[str], None] = '485611de3056'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Remove orphaned job rows and first_run flags for the old monolithic
    intraday workers that have been replaced by the hourly-only workers
    and the nightly W/M orchestrator stages."""
    bind = op.get_bind()
    # Delete old job definitions/tracking rows
    bind.execute(
        text("DELETE FROM jobs WHERE job_key IN ('job.ticker_intraday_update', 'job.ticker_intraday_indicators')")
    )
    # Delete old first_run systemconfig flags
    bind.execute(
        text("DELETE FROM system_config WHERE key IN ('first_run.ticker_intraday_update', 'first_run.ticker_intraday_indicators')")
    )


def downgrade() -> None:
    """Downgrade is intentionally a no-op. The old job rows would be
    recreated by `register_all_jobs()` + `sync_all_jobs_to_db()` on
    the next app startup if this migration were rolled back and the
    old code were still present."""
    pass
