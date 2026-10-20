"""add ai provider routes and credentials tables and seed oauth routes

Revision ID: k11111111111
Revises: j88888888888
Create Date: 2026-10-20 00:00:00.000000
"""
import hashlib
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "k11111111111"
down_revision: Union[str, Sequence[str], None] = "j88888888888"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OAUTH_SEED_PROVIDERS = [
    ("codex", "Codex"),
    ("antigravity", "Antigravity"),
    ("claude", "Claude"),
    ("xai", "xAI"),
    ("kimi", "Kimi"),
    ("kimi-ai", "Kimi AI"),
    ("meta", "Meta"),
    ("devin", "Devin"),
]


def upgrade() -> None:
    conn = op.get_bind()
    tables = set(sa.inspect(conn).get_table_names())

    if "ai_provider_routes" not in tables:
        op.create_table(
            "ai_provider_routes",
            sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
            sa.Column("kind", sa.String(length=32), nullable=False),
            sa.Column("provider", sa.String(length=64), nullable=False),
            sa.Column("display_label", sa.String(length=128), nullable=False),
            sa.Column("proxy_prefix", sa.String(length=64), nullable=True),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.Column("config_json", sa.Text(), nullable=True, server_default=sa.text("'{}'")),
            sa.Column("created_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        )
        op.create_index(
            "ix_ai_provider_routes_proxy_prefix",
            "ai_provider_routes",
            ["proxy_prefix"],
            unique=True,
        )

    if "ai_provider_credentials" not in tables:
        op.create_table(
            "ai_provider_credentials",
            sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
            sa.Column(
                "route_id",
                sa.String(length=64),
                sa.ForeignKey("ai_provider_routes.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("kind", sa.String(length=32), nullable=False),
            sa.Column("vault_reference", sa.String(length=128), nullable=False),
            sa.Column("proxy_credential_name", sa.String(length=128), nullable=False),
            sa.Column("masked_identity", sa.String(length=128), nullable=False, server_default=sa.text("''")),
            sa.Column("priority", sa.Integer(), nullable=False, server_default=sa.text("1")),
            sa.Column("weight", sa.Integer(), nullable=False, server_default=sa.text("1")),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'active'")),
            sa.Column("cooldown", sa.DateTime(timezone=False), nullable=True),
            sa.Column("last_redacted_error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        )
        op.create_index(
            "ix_ai_provider_credentials_route_id",
            "ai_provider_credentials",
            ["route_id"],
            unique=False,
        )

    # Seed OAuth routes idempotently
    for provider, display_label in OAUTH_SEED_PROVIDERS:
        route_id = f"oauth:{provider}"
        proxy_prefix = f"blm-{hashlib.sha256(route_id.encode('utf-8')).hexdigest()[:16]}"
        conn.execute(
            sa.text(
                """
                INSERT OR IGNORE INTO ai_provider_routes (
                    id, kind, provider, display_label, proxy_prefix, enabled, config_json, created_at, updated_at
                ) VALUES (
                    :id, 'oauth', :provider, :display_label, :proxy_prefix, 1, '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                """
            ),
            {
                "id": route_id,
                "provider": provider,
                "display_label": display_label,
                "proxy_prefix": proxy_prefix,
            },
        )


def downgrade() -> None:
    conn = op.get_bind()
    tables = set(sa.inspect(conn).get_table_names())

    if "ai_provider_credentials" in tables:
        op.drop_table("ai_provider_credentials")

    if "ai_provider_routes" in tables:
        op.drop_table("ai_provider_routes")
