"""seed app version into system config

Revision ID: x123456789abm
Revises: x123456789abk
Create Date: 2026-05-19 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "x123456789abm"
down_revision = "x123456789abk"
branch_labels = None
depends_on = None

APP_VERSION = "1.0.0"


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "INSERT OR IGNORE INTO system_config (key, value, updated_at) "
            "VALUES (:key, :value, CURRENT_TIMESTAMP)"
        ),
        {"key": "app.version", "value": APP_VERSION},
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text("DELETE FROM system_config WHERE key = :key"),
        {"key": "app.version"},
    )
