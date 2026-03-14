"""add_news_articles

Revision ID: e2a8f91c3b7d
Revises: c55ade594ba5
Create Date: 2026-03-14 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e2a8f91c3b7d"
down_revision: Union[str, Sequence[str], None] = "c55ade594ba5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "news_articles",
        sa.Column("url", sa.String(2048), primary_key=True, index=True, nullable=False),
        sa.Column("source", sa.String(64), nullable=False, index=True),
        sa.Column("title", sa.String(512), nullable=True),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("authors", sa.JSON(), nullable=True),
        sa.Column("top_image", sa.String(2048), nullable=True),
        sa.Column("publish_date", sa.DateTime(), nullable=True, index=True),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_news_articles_source_publish",
        "news_articles",
        ["source", "publish_date"],
    )


def downgrade() -> None:
    op.drop_index("ix_news_articles_source_publish", table_name="news_articles")
    op.drop_table("news_articles")
