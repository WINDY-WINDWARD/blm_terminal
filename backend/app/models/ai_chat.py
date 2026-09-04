"""SQLAlchemy ORM models for persistent AI chat history."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ChatSession(Base):
    """A single chat conversation thread."""

    __tablename__ = "chat_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, default=1)
    title: Mapped[str] = mapped_column(String(120), nullable=False, default="New Chat")
    model: Mapped[str] = mapped_column(String(64), nullable=False, default="minimax-m2-5-free")
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    exchange: Mapped[str] = mapped_column(String(16), nullable=False, default="NSE")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    messages: Mapped[list["ChatMessageRecord"]] = relationship(
        "ChatMessageRecord",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatMessageRecord.id",
    )
    user = relationship("User", backref="chat_sessions")


class ChatMessageRecord(Base):
    """A single message turn within a chat session."""

    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # 'user' | 'assistant'
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # JSON-serialised list of tool call names for display (assistant only, optional)
    tool_calls_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=func.now(), nullable=False
    )

    session: Mapped[ChatSession] = relationship("ChatSession", back_populates="messages")
