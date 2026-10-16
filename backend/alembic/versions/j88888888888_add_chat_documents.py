"""add chat documents and pdf full-text search

Revision ID: j88888888888
Revises: i77777777777
Create Date: 2026-10-16 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "j88888888888"
down_revision: Union[str, Sequence[str], None] = "i77777777777"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    tables = set(sa.inspect(conn).get_table_names())

    if "chat_documents" not in tables:
        op.create_table(
            "chat_documents",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("filename", sa.String(255), nullable=False),
            sa.Column("storage_key", sa.String(512), nullable=False),
            sa.Column("file_type", sa.String(16), nullable=False),
            sa.Column("mime_type", sa.String(128), nullable=False, server_default="application/octet-stream"),
            sa.Column("file_size", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("sha256", sa.String(64), nullable=False),
            sa.Column("row_count", sa.Integer(), nullable=True),
            sa.Column("page_count", sa.Integer(), nullable=True),
            sa.Column("needs_ocr", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("is_inlineable", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("summary_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("user_id", "sha256", name="uq_chat_documents_user_sha"),
        )
        op.create_index("ix_chat_documents_user", "chat_documents", ["user_id"])

    if "chat_document_sessions" not in tables:
        op.create_table(
            "chat_document_sessions",
            sa.Column("document_id", sa.Integer(), sa.ForeignKey("chat_documents.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("session_id", sa.Integer(), sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("attached_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_chat_document_sessions_session", "chat_document_sessions", ["session_id"])

    if "chat_document_pages" not in tables:
        op.create_table(
            "chat_document_pages",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("document_id", sa.Integer(), sa.ForeignKey("chat_documents.id", ondelete="CASCADE"), nullable=False),
            sa.Column("page_number", sa.Integer(), nullable=False),
            sa.Column("content", sa.Text(), nullable=False, server_default=""),
            sa.UniqueConstraint("document_id", "page_number", name="uq_chat_document_pages_doc_page"),
        )
        op.create_index("ix_chat_document_pages_document", "chat_document_pages", ["document_id"])

    message_columns = {col["name"] for col in sa.inspect(conn).get_columns("chat_messages")}
    if "attachments_json" not in message_columns:
        op.add_column("chat_messages", sa.Column("attachments_json", sa.Text(), nullable=True))

    op.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS pdf_pages_fts USING fts5("
        "document_id UNINDEXED, page_number UNINDEXED, content, tokenize='porter')"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS pdf_pages_fts")
    conn = op.get_bind()
    tables = set(sa.inspect(conn).get_table_names())
    if "chat_document_pages" in tables:
        op.drop_index("ix_chat_document_pages_document", table_name="chat_document_pages")
        op.drop_table("chat_document_pages")
    if "chat_document_sessions" in tables:
        op.drop_index("ix_chat_document_sessions_session", table_name="chat_document_sessions")
        op.drop_table("chat_document_sessions")
    if "chat_documents" in tables:
        op.drop_index("ix_chat_documents_user", table_name="chat_documents")
        op.drop_table("chat_documents")

    message_columns = {col["name"] for col in sa.inspect(conn).get_columns("chat_messages")}
    if "attachments_json" in message_columns:
        op.drop_column("chat_messages", "attachments_json")
