"""add_news_nlp_fields

Add NLP processing fields to news_articles table for multi-source RSS aggregation.
Adds sentiment, entities, threat classification, language detection, and source credibility.

Revision ID: x123456789newsnlp
Revises: 4cb23a53b80a
Create Date: 2026-05-27 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
import sqlalchemy.exc as sqla_exc

revision: str = "x123456789newsnlp"
down_revision: Union[str, Sequence[str], None] = "4cb23a53b80a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _add_col_if_not_exists(col_name: str, col_def: sa.Column, table_name: str = "news_articles") -> None:
    """Add a column only if it does not already exist (idempotent migration for SQLite)."""
    try:
        op.add_column(table_name, col_def)
    except sqla_exc.OperationalError as e:
        if "duplicate column name" in str(e).lower():
            pass  # column already exists, safe to skip
        else:
            raise


def upgrade() -> None:
    """Add NLP fields to news_articles table."""
    # Sentiment analysis fields
    _add_col_if_not_exists(
        "sentiment",
        sa.Column("sentiment", sa.String(16), nullable=True),
    )
    _add_col_if_not_exists(
        "sentiment_score",
        sa.Column("sentiment_score", sa.Float, nullable=True),
    )
    _add_col_if_not_exists(
        "confidence",
        sa.Column("confidence", sa.Float, nullable=True),
    )

    # Language detection
    _add_col_if_not_exists(
        "language",
        sa.Column("language", sa.String(8), nullable=True),
    )

    # Entity extraction
    _add_col_if_not_exists(
        "entities",
        sa.Column("entities", sa.JSON, nullable=True),
    )

    # Threat classification
    _add_col_if_not_exists(
        "threat_level",
        sa.Column("threat_level", sa.String(16), nullable=True),
    )
    _add_col_if_not_exists(
        "threat_category",
        sa.Column("threat_category", sa.String(32), nullable=True),
    )

    # Source credibility
    _add_col_if_not_exists(
        "source_credibility",
        sa.Column("source_credibility", sa.String(16), nullable=True),
    )

    # Add indexes for frequently filtered columns
    _create_index_if_not_exists("ix_news_articles_sentiment", "news_articles", "sentiment")
    _create_index_if_not_exists("ix_news_articles_threat_level", "news_articles", "threat_level")


def _create_index_if_not_exists(index_name: str, table_name: str, column_name: str) -> None:
    """Create an index only if it does not already exist."""
    try:
        op.create_index(index_name, table_name, [column_name], unique=False)
    except sqla_exc.OperationalError as e:
        if "duplicate index name" in str(e).lower() or "already exists" in str(e).lower():
            pass  # index already exists, safe to skip
        else:
            raise


def downgrade() -> None:
    """Remove NLP fields from news_articles table."""
    op.drop_index("ix_news_articles_sentiment", table_name="news_articles")
    op.drop_index("ix_news_articles_threat_level", table_name="news_articles")
    op.drop_column("news_articles", "source_credibility")
    op.drop_column("news_articles", "threat_category")
    op.drop_column("news_articles", "threat_level")
    op.drop_column("news_articles", "entities")
    op.drop_column("news_articles", "language")
    op.drop_column("news_articles", "confidence")
    op.drop_column("news_articles", "sentiment_score")
    op.drop_column("news_articles", "sentiment")
