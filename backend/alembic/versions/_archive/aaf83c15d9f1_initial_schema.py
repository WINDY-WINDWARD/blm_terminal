"""initial_schema

Revision ID: aaf83c15d9f1
Revises:
Create Date: 2026-03-04 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import sqlite

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "aaf83c15d9f1"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "corporate_filings",
        sa.Column("symbol", sa.String(32), primary_key=True, index=True, nullable=False),
        sa.Column("csv_data", sa.Text(), nullable=False),
        sa.Column("last_fetched_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "stock_universe",
        sa.Column("symbol", sa.String(32), primary_key=True, index=True, nullable=False),
        sa.Column("company_name", sa.String(255), nullable=False),
        sa.Column("segment", sa.String(64), nullable=False),
        sa.Column("industry", sa.String(255), nullable=False),
        sa.Column("sector_pe", sa.Float(), nullable=True),
        sa.Column("symbol_pe", sa.Float(), nullable=True),
        sa.Column("industry_info", sqlite.JSON(), nullable=False),
        sa.Column("last_update_time", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("stock_universe")
    op.drop_table("corporate_filings")
