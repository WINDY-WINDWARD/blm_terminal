"""add_company_symbol_to_news_articles

Revision ID: f1a3b7c92d4e
Revises: e2a8f91c3b7d
Create Date: 2026-03-14 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f1a3b7c92d4e"
down_revision: Union[str, Sequence[str], None] = "e2a8f91c3b7d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "news_articles",
        sa.Column("company_symbol", sa.String(32), nullable=True),
    )
    op.create_index(
        "ix_news_articles_company_symbol",
        "news_articles",
        ["company_symbol"],
    )


def downgrade() -> None:
    op.drop_index("ix_news_articles_company_symbol", table_name="news_articles")
    op.drop_column("news_articles", "company_symbol")
