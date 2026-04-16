"""seed notif system config defaults

Revision ID: x123456789abk
Revises: x123456789abj
Create Date: 2026-04-16 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "x123456789abk"
down_revision = "x123456789abj"
branch_labels = None
depends_on = None


DEFAULTS = {
    "notif.rsi_oversold_threshold": "30.0",
    "notif.rsi_overbought_threshold": "70.0",
    "notif.volatility_spike_ratio": "1.5",
    "notif.atr_expansion_threshold": "4.0",
    "notif.momentum_surge_threshold": "70.0",
    "notif.return_1w_spike_threshold": "10.0",
    "notif.streak_days_threshold": "5.0",
    "notif.near_52w_threshold": "3.0",
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
