"""seed deal significance config defaults

Revision ID: x123456789abl
Revises: x123456789abk
Create Date: 2026-05-07 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "x123456789abl"
down_revision = "x123456789abk"
branch_labels = None
depends_on = None


DEFAULTS = {
    # Fraction of market cap: deal value must exceed this to be significant.
    # 0.05 = 5% of market cap.
    "notif.deal_significance_pct": "0.05",
    # Absolute fallback threshold in Rs Cr when market cap is unknown.
    "notif.deal_absolute_threshold_cr": "2.0",
}


def upgrade() -> None:
    bind = op.get_bind()
    for key, value in DEFAULTS.items():
        bind.execute(
            sa.text(
                "INSERT OR IGNORE INTO system_config (key, value, updated_at) "
                "VALUES (:key, :value, CURRENT_TIMESTAMP)"
            ),
            {"key": key, "value": value},
        )


def downgrade() -> None:
    bind = op.get_bind()
    for key in DEFAULTS:
        bind.execute(sa.text("DELETE FROM system_config WHERE key = :key"), {"key": key})
