"""Add uq_market_stock_symbol (converge DBs with the ORM model)

Revision ID: f44444444444
Revises: f33333333333
Create Date: 2026-09-22 04:00:00.000000

The ORM model declares UniqueConstraint("symbol") on market_category_stocks,
but no migration ever created it (the squash migration and
6904a6732334_add_missing_unique_constraints only created plain non-unique
indexes). Any DB built through Alembic therefore lacks the arbiter that
market_local_sync's ON CONFLICT (symbol) upsert needs, and every sync cycle
failed with "ON CONFLICT clause does not match any PRIMARY KEY or UNIQUE
constraint" — rolling back the whole transaction and leaving both market
tables empty (empty Analysis tab).

Note: market_categories needs no change — its composite PRIMARY KEY
(category_type, slug) already covers its upsert arbiter (verified against a
live DB). Only market_category_stocks is converged here.

Pre-dedupe keeps the latest last_updated row per symbol so index creation
cannot fail on installs that accumulated duplicates while the upsert was
broken.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = 'f44444444444'
down_revision: Union[str, Sequence[str], None] = 'f33333333333'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_DEDUPE_SQL = """
DELETE FROM market_category_stocks
WHERE id NOT IN (
    SELECT id FROM (
        SELECT id,
               ROW_NUMBER() OVER (
                   PARTITION BY symbol ORDER BY last_updated DESC, id DESC
               ) AS rn
        FROM market_category_stocks
    )
    WHERE rn = 1
)
"""


def upgrade() -> None:
    conn = op.get_bind()
    existing = {ix["name"] for ix in inspect(conn).get_indexes("market_category_stocks")}
    if "uq_market_stock_symbol" in existing:
        return
    conn.execute(sa.text(_DEDUPE_SQL))
    op.create_index(
        "uq_market_stock_symbol",
        "market_category_stocks",
        ["symbol"],
        unique=True,
    )


def downgrade() -> None:
    conn = op.get_bind()
    existing = {ix["name"] for ix in inspect(conn).get_indexes("market_category_stocks")}
    if "uq_market_stock_symbol" in existing:
        op.drop_index("uq_market_stock_symbol", table_name="market_category_stocks")
