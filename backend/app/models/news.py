"""SQLAlchemy ORM model for cached news articles."""

from datetime import datetime

from sqlalchemy import DateTime, Float, Index, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class NewsArticle(Base):
    """ORM model for cached news articles from external sources."""

    __tablename__ = "news_articles"

    url: Mapped[str] = mapped_column(
        String(2048),
        primary_key=True,
        index=True,
    )
    source: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    authors: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    top_image: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    publish_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False),
        nullable=True,
        index=True,
    )
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        default=func.now(),
    )
    company_symbol: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        index=True,
    )

    # ── NLP Fields (added for multi-source RSS) ────────────────────────────────

    # Sentiment analysis
    sentiment: Mapped[str | None] = mapped_column(
        String(16),
        nullable=True,
        index=True,
    )  # BULLISH, BEARISH, NEUTRAL
    sentiment_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )  # -1.0 to 1.0
    confidence: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )  # 0.0 to 1.0

    # Language detection
    language: Mapped[str | None] = mapped_column(
        String(8),
        nullable=True,
        index=True,
    )  # en, zh, ja, ko, ru, ar, hi, etc.

    # Entity extraction
    entities: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )  # {"countries": [], "organizations": [], "people": [], "tickers": []}

    # Threat classification
    threat_level: Mapped[str | None] = mapped_column(
        String(16),
        nullable=True,
        index=True,
    )  # CRITICAL, HIGH, MEDIUM, LOW
    threat_category: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
    )  # conflict, market, cyber, natural, regulatory

    # Source credibility
    source_credibility: Mapped[str | None] = mapped_column(
        String(16),
        nullable=True,
    )  # STATE_MEDIA, CAUTION, NONE

    # ── iinvest fields ────────────────────────────────────────────────────────
    iinvest_story_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        unique=True,
        index=True,
    )
    iinvest_published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )

    __table_args__ = (
        Index("ix_news_articles_source_publish", "source", "publish_date"),
    )
