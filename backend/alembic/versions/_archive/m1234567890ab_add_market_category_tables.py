"""add_market_category_tables

Revision ID: m1234567890ab
Revises: a1b2c3d4e5f6
Create Date: 2026-03-14 15:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "m1234567890ab"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "market_categories",
        sa.Column("category_type", sa.String(32), nullable=False),
        sa.Column("slug", sa.String(128), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("url", sa.String(512), nullable=True),
        sa.Column("market_cap", sa.Float, nullable=True),
        sa.Column("pe", sa.Float, nullable=True),
        sa.Column("advance", sa.Integer, nullable=True),
        sa.Column("decline", sa.Integer, nullable=True),
        sa.Column("sentiment", sa.String(32), nullable=True),
        sa.Column("earnings_yoy", sa.Float, nullable=True),
        sa.Column("last_updated", sa.DateTime, nullable=False),
        sa.Column(
            "created_at", sa.DateTime, server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("category_type", "slug"),
    )

    op.create_index(
        "ix_market_categories_type_slug",
        "market_categories",
        ["category_type", "slug"],
        unique=False,
    )

    op.create_table(
        "market_category_stocks",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("category_type", sa.String(32), nullable=False),
        sa.Column("category_slug", sa.String(128), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("company_name", sa.String(255), nullable=False),
        sa.Column("exchange", sa.String(16), nullable=True),
        sa.Column("curr_price", sa.Float, nullable=True),
        sa.Column("per_change", sa.Float, nullable=True),
        sa.Column("market_cap", sa.Float, nullable=True),
        sa.Column("ttm_pe", sa.Float, nullable=True),
        sa.Column("net_profit", sa.Float, nullable=True),
        sa.Column("net_profit_yoy", sa.Float, nullable=True),
        sa.Column("tech_trend", sa.String(32), nullable=True),
        sa.Column("mc_url", sa.String(512), nullable=True),
        sa.Column("last_updated", sa.DateTime, nullable=False),
        sa.Column(
            "created_at", sa.DateTime, server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "category_type", "category_slug", "symbol", name="uq_category_stock"
        ),
    )

    op.create_index(
        "ix_market_category_stocks_category",
        "market_category_stocks",
        ["category_type", "category_slug"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("market_category_stocks")
    op.drop_table("market_categories")
