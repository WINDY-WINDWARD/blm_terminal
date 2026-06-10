"""merge_market_category_stocks

Revision ID: m9876543210ab
Revises: m1234567890ab
Create Date: 2026-03-15 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "m9876543210ab"
down_revision: Union[str, Sequence[str], None] = "m1234567890ab"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create temporary table with new schema (unique by symbol, categories as JSON)
    op.create_table(
        "market_category_stocks_new",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(32), nullable=False, unique=True),
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
        sa.Column("categories", sa.JSON, nullable=False),
        sa.Column("last_updated", sa.DateTime, nullable=False),
        sa.Column(
            "created_at", sa.DateTime, server_default=sa.func.now(), nullable=False
        ),
    )

    # Create index on symbol
    op.create_index(
        "ix_market_category_stocks_new_symbol", "market_category_stocks_new", ["symbol"]
    )

    # Migrate data: aggregate categories for each symbol
    # This is a simplified migration - we'll re-fetch all data anyway
    # Just copy over the basic data, categories will be refreshed by the scheduler
    op.execute("""
        INSERT INTO market_category_stocks_new (symbol, company_name, exchange, curr_price, per_change, market_cap, ttm_pe, net_profit, net_profit_yoy, tech_trend, mc_url, categories, last_updated, created_at)
        SELECT 
            symbol,
            company_name,
            exchange,
            curr_price,
            per_change,
            market_cap,
            ttm_pe,
            net_profit,
            net_profit_yoy,
            tech_trend,
            mc_url,
            json_array(json_object('type', category_type, 'slug', category_slug)),
            last_updated,
            created_at
        FROM market_category_stocks
        GROUP BY symbol
    """)

    # Drop old table
    op.drop_table("market_category_stocks")

    # Rename new table
    op.rename_table("market_category_stocks_new", "market_category_stocks")


def downgrade() -> None:
    # This is complex to reverse - just recreate the old structure
    op.create_table(
        "market_category_stocks_old",
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
    )

    op.execute("""
        INSERT INTO market_category_stocks_old (category_type, category_slug, symbol, company_name, exchange, curr_price, per_change, market_cap, ttm_pe, net_profit, net_profit_yoy, tech_trend, mc_url, last_updated, created_at)
        SELECT 
            json_extract(value, '$.type') as category_type,
            json_extract(value, '$.slug') as category_slug,
            symbol, company_name, exchange, curr_price, per_change, market_cap, ttm_pe, net_profit, net_profit_yoy, tech_trend, mc_url, last_updated, created_at
        FROM market_category_stocks,
             json_each(categories)
    """)

    op.drop_table("market_category_stocks")
    op.rename_table("market_category_stocks_old", "market_category_stocks")
