"""SQLAlchemy ORM model for cached news articles."""

from datetime import datetime

from sqlalchemy import DateTime, Index, JSON, String, Text, func
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
        server_default=func.now(),
    )
    company_symbol: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        index=True,
    )

    __table_args__ = (
        Index("ix_news_articles_source_publish", "source", "publish_date"),
    )
