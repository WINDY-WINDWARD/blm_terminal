"""SQLAlchemy ORM models for persistent AI chat history."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, backref, mapped_column, relationship

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
    document_links: Mapped[list["ChatDocumentSession"]] = relationship(
        "ChatDocumentSession",
        back_populates="session",
        cascade="all, delete-orphan",
    )
    user = relationship("User", backref=backref("chat_sessions", passive_deletes=True))


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
    attachments_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=func.now(), nullable=False
    )

    session: Mapped[ChatSession] = relationship("ChatSession", back_populates="messages")


class ChatDocument(Base):
    """A user-owned PDF or CSV in the chat document library."""

    __tablename__ = "chat_documents"
    __table_args__ = (UniqueConstraint("user_id", "sha256", name="uq_chat_documents_user_sha"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    file_type: Mapped[str] = mapped_column(String(16), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False, default="application/octet-stream")
    file_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    needs_ocr: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_inlineable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    summary_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=func.now(), nullable=False)

    session_links: Mapped[list["ChatDocumentSession"]] = relationship(
        "ChatDocumentSession",
        back_populates="document",
        cascade="all, delete-orphan",
    )
    pages: Mapped[list["ChatDocumentPage"]] = relationship(
        "ChatDocumentPage",
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="ChatDocumentPage.page_number",
    )


class ChatDocumentSession(Base):
    """Association between a library document and a chat session."""

    __tablename__ = "chat_document_sessions"

    document_id: Mapped[int] = mapped_column(
        ForeignKey("chat_documents.id", ondelete="CASCADE"), primary_key=True
    )
    session_id: Mapped[int] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    attached_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=func.now(), nullable=False)

    document: Mapped[ChatDocument] = relationship("ChatDocument", back_populates="session_links")
    session: Mapped[ChatSession] = relationship("ChatSession", back_populates="document_links")


class ChatDocumentPage(Base):
    """One extracted PDF page belonging to a chat document."""

    __tablename__ = "chat_document_pages"
    __table_args__ = (UniqueConstraint("document_id", "page_number", name="uq_chat_document_pages_doc_page"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("chat_documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")

    document: Mapped[ChatDocument] = relationship("ChatDocument", back_populates="pages")
