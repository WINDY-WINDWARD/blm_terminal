"""add iinvest columns to news_articles

Adds iinvest_story_id (unique-indexed for dedup) and iinvest_published_at
to the news_articles table. The iinvest integration uses iinvest_story_id
as the upsert key for company news fetched from iinvest.cogencis.com.

Revision ID: 31a1b2c3d4e6
Revises: 31a1b2c3d4e5
Create Date: 2026-06-18 12:00:01.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "31a1b2c3d4e6"
down_revision: Union[str, Sequence[str], None] = "31a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add iinvest fields to news_articles."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {c["name"] for c in inspector.get_columns("news_articles")}
    existing_indexes = {i["name"] for i in inspector.get_indexes("news_articles")}
    with op.batch_alter_table("news_articles", schema=None) as batch_op:
        if "iinvest_story_id" not in existing:
            batch_op.add_column(
                sa.Column("iinvest_story_id", sa.String(length=64), nullable=True)
            )
        if "iinvest_published_at" not in existing:
            batch_op.add_column(
                sa.Column(
                    "iinvest_published_at",
                    sa.DateTime(timezone=False),
                    nullable=True,
                )
            )
        if "ix_news_articles_iinvest_story_id" not in existing_indexes:
            batch_op.create_index(
                batch_op.f("ix_news_articles_iinvest_story_id"),
                ["iinvest_story_id"],
                unique=True,
            )


def downgrade() -> None:
    """Remove iinvest fields from news_articles."""
    with op.batch_alter_table("news_articles", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_news_articles_iinvest_story_id"))
        batch_op.drop_column("iinvest_published_at")
        batch_op.drop_column("iinvest_story_id")
