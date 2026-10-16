"""Chat document ingestion and retrieval utilities.

CSV uploads are materialised as per-document SQLite tables; PDF uploads are
stored page-by-page and indexed in SQLite FTS5.  The AI agent only receives
read-only tools and ownership-checked document identifiers.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import re
import sqlite3
import uuid
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models.ai_chat import ChatDocument, ChatDocumentPage, ChatDocumentSession

logger = logging.getLogger(__name__)

MAX_FILE_SIZE = 50 * 1024 * 1024
MAX_ATTACHMENTS_PER_TURN = 5
MAX_CSV_QUERY_ROWS = 50
MAX_PDF_PAGES_PER_READ = 5
MAX_PDF_READ_CHARS = 20_000
PDF_INLINE_MAX_PAGES = 5
PDF_INLINE_MAX_CHARS = 12_000


class DocumentError(ValueError):
    """Raised for user-correctable upload or document errors."""


def _uploads_root() -> Path:
    root = Path(settings.db_path).expanduser().resolve().parent / "uploads"
    root.mkdir(parents=True, exist_ok=True)
    return root


def document_file_path(document: ChatDocument) -> Path:
    """Return the on-disk path for a stored document."""
    return _uploads_root() / document.storage_key


def _safe_filename(name: str) -> str:
    base = Path(name or "document").name
    base = re.sub(r"[\x00-\x1f]+", "", base).strip()
    return (base or "document")[:255]


def _detect_file_type(filename: str, mime_type: str | None) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf" or (mime_type or "").lower() == "application/pdf":
        return "pdf"
    if suffix in (".csv", ".tsv") or "csv" in (mime_type or "").lower():
        return "csv"
    raise DocumentError("Unsupported file type. Upload a .pdf, .csv, or .tsv file.")


def _sanitize_columns(columns: list[Any]) -> list[str]:
    used: set[str] = set()
    safe: list[str] = []
    for index, raw in enumerate(columns, start=1):
        name = re.sub(r"[^0-9a-zA-Z_]+", "_", str(raw)).strip("_") or f"column_{index}"
        if name[0].isdigit():
            name = f"col_{name}"
        candidate = name
        suffix = 2
        while candidate.lower() in used:
            candidate = f"{name}_{suffix}"
            suffix += 1
        used.add(candidate.lower())
        safe.append(candidate)
    return safe


def _json_safe(value: Any) -> Any:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (int, float, bool, str)):
        return value
    return str(value)


def _connect_sync() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _write_file(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _ingest_csv_sync(staging_table: str, content: bytes) -> tuple[dict[str, Any], int]:
    try:
        frame = pd.read_csv(io.BytesIO(content), sep=None, engine="python", on_bad_lines="skip")
    except Exception as exc:  # noqa: BLE001 - user input errors are surfaced verbatim
        raise DocumentError(f"Could not parse CSV: {exc}") from exc

    if frame.shape[1] == 0:
        raise DocumentError("CSV file has no columns.")

    original_columns = [str(col) for col in frame.columns]
    safe_columns = _sanitize_columns(original_columns)
    frame.columns = safe_columns
    row_count = int(len(frame))

    columns_summary = []
    for original, safe_name in zip(original_columns, safe_columns):
        series = frame[safe_name]
        samples = [_json_safe(value) for value in series.dropna().head(3).tolist()]
        columns_summary.append(
            {
                "name": original,
                "sqlite_name": safe_name,
                "dtype": str(series.dtype),
                "null_count": int(series.isna().sum()),
                "sample_values": samples,
            }
        )

    sample_rows = json.loads(frame.head(3).to_json(orient="records"))
    summary = {"columns": columns_summary, "sample_rows": sample_rows}

    conn = _connect_sync()
    try:
        frame.to_sql(staging_table, conn, if_exists="replace", index=False, chunksize=1000)
        conn.commit()
    except Exception as exc:  # noqa: BLE001
        conn.execute(f'DROP TABLE IF EXISTS "{staging_table}"')
        conn.commit()
        raise DocumentError(f"Could not load CSV into the local database: {exc}") from exc
    finally:
        conn.close()
    return summary, row_count


def _flatten_outline(reader: Any, items: Any, depth: int = 0) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    if not items:
        return nodes
    for item in items:
        if isinstance(item, list):
            nodes.extend(_flatten_outline(reader, item, depth + 1))
            continue
        title = getattr(item, "title", None) or (item.get("title") if isinstance(item, dict) else None)
        try:
            page_number = reader.get_destination_page_number(item) + 1
        except Exception:  # noqa: BLE001 - malformed bookmarks fall back to depth only
            page_number = None
        nodes.append({"depth": depth, "title": str(title or "Untitled"), "page_number": page_number})
    return nodes


def _ingest_pdf_sync(content: bytes) -> tuple[dict[str, Any], int, bool, bool, list[str]]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - packaging guard
        raise DocumentError("PDF support is not installed. Add pypdf to the backend environment.") from exc

    try:
        reader = PdfReader(io.BytesIO(content))
        if reader.is_encrypted:
            try:
                decrypted = reader.decrypt("")
            except Exception:  # noqa: BLE001
                decrypted = 0
            if not decrypted:
                raise DocumentError("This PDF is password protected and cannot be read.")
        pages: list[str] = []
        for page in reader.pages:
            try:
                text = page.extract_text() or ""
            except Exception as exc:  # noqa: BLE001
                logger.warning("PDF page extraction failed: %s", exc)
                text = ""
            pages.append(text.strip())
    except DocumentError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise DocumentError(f"Could not read PDF: {exc}") from exc

    page_count = len(pages)
    total_chars = sum(len(text) for text in pages)
    needs_ocr = page_count > 0 and total_chars < max(10, page_count * 10)
    is_inlineable = page_count <= PDF_INLINE_MAX_PAGES and total_chars <= PDF_INLINE_MAX_CHARS
    outline = _flatten_outline(reader, getattr(reader, "outline", []) or [])
    summary = {
        "outline": outline,
        "empty_pages": [index + 1 for index, text in enumerate(pages) if not text],
        "total_chars": total_chars,
    }
    return summary, page_count, needs_ocr, is_inlineable, pages


def _rename_table(staging_table: str, target_table: str) -> None:
    conn = _connect_sync()
    try:
        conn.execute(f'ALTER TABLE "{staging_table}" RENAME TO "{target_table}"')
        conn.commit()
    finally:
        conn.close()


def _drop_table(table_name: str) -> None:
    if not re.fullmatch(r"csv_doc_\d+|csv_stage_[0-9a-f]+", table_name):
        raise DocumentError("Refusing to drop an unexpected table name.")
    conn = _connect_sync()
    try:
        conn.execute(f'DROP TABLE IF EXISTS "{table_name}"')
        conn.commit()
    finally:
        conn.close()


def _write_pdf_fts(document_id: int, pages: list[str]) -> None:
    conn = _connect_sync()
    try:
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS pdf_pages_fts USING fts5(document_id UNINDEXED, page_number UNINDEXED, content, tokenize='porter')")
        conn.execute("DELETE FROM pdf_pages_fts WHERE document_id = ?", (document_id,))
        conn.executemany(
            "INSERT INTO pdf_pages_fts(document_id, page_number, content) VALUES (?, ?, ?)",
            [(document_id, index + 1, text) for index, text in enumerate(pages)],
        )
        conn.commit()
    finally:
        conn.close()


def _delete_pdf_fts(document_id: int) -> None:
    conn = _connect_sync()
    try:
        conn.execute("DELETE FROM pdf_pages_fts WHERE document_id = ?", (document_id,))
        conn.commit()
    finally:
        conn.close()


async def create_document(
    db: AsyncSession,
    user_id: int,
    filename: str,
    content: bytes,
    mime_type: str | None = None,
) -> ChatDocument:
    if len(content) > MAX_FILE_SIZE:
        raise DocumentError("File is larger than the 50 MB limit.")
    if not content:
        raise DocumentError("Uploaded file is empty.")

    safe_name = _safe_filename(filename)
    file_type = _detect_file_type(safe_name, mime_type)
    sha256 = hashlib.sha256(content).hexdigest()

    existing = (
        await db.execute(
            select(ChatDocument).where(ChatDocument.user_id == user_id, ChatDocument.sha256 == sha256)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    suffix = Path(safe_name).suffix.lower() or (".pdf" if file_type == "pdf" else ".csv")
    storage_key = f"{user_id}/{sha256}{suffix}"
    await asyncio.to_thread(_write_file, _uploads_root() / storage_key, content)

    staging_table: str | None = None
    pages: list[str] | None = None
    if file_type == "csv":
        staging_table = f"csv_stage_{uuid.uuid4().hex[:12]}"
        summary, row_count = await asyncio.to_thread(_ingest_csv_sync, staging_table, content)
        page_count = None
        needs_ocr = False
        is_inlineable = False
    else:
        summary, page_count, needs_ocr, is_inlineable, pages = await asyncio.to_thread(
            _ingest_pdf_sync, content
        )
        row_count = None

    document = ChatDocument(
        user_id=user_id,
        filename=safe_name,
        storage_key=storage_key,
        file_type=file_type,
        mime_type=mime_type or ("application/pdf" if file_type == "pdf" else "text/csv"),
        file_size=len(content),
        sha256=sha256,
        row_count=row_count,
        page_count=page_count,
        needs_ocr=needs_ocr,
        is_inlineable=is_inlineable,
        summary_json=json.dumps(summary),
    )
    db.add(document)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        if staging_table:
            await asyncio.to_thread(_drop_table, staging_table)
        existing = (
            await db.execute(
                select(ChatDocument).where(ChatDocument.user_id == user_id, ChatDocument.sha256 == sha256)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing
        raise

    document_id = document.id

    try:
        if file_type == "csv":
            await db.commit()
            await asyncio.to_thread(_rename_table, staging_table, f"csv_doc_{document_id}")
        else:
            for index, text in enumerate(pages or [], start=1):
                db.add(ChatDocumentPage(document_id=document_id, page_number=index, content=text))
            await db.commit()
            await asyncio.to_thread(_write_pdf_fts, document_id, pages or [])
    except Exception:
        await db.rollback()
        if staging_table:
            await asyncio.to_thread(_drop_table, staging_table)
        stale = (await db.execute(select(ChatDocument).where(ChatDocument.id == document_id))).scalar_one_or_none()
        if stale is not None:
            await db.delete(stale)
            await db.commit()
        raise

    return document


async def list_documents(db: AsyncSession, user_id: int) -> list[ChatDocument]:
    result = await db.execute(
        select(ChatDocument)
        .options(selectinload(ChatDocument.session_links))
        .where(ChatDocument.user_id == user_id)
        .order_by(ChatDocument.created_at.desc())
    )
    return list(result.scalars().all())


async def get_document(db: AsyncSession, user_id: int, document_id: int) -> ChatDocument | None:
    result = await db.execute(
        select(ChatDocument)
        .options(selectinload(ChatDocument.session_links))
        .where(ChatDocument.id == document_id, ChatDocument.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def delete_document(db: AsyncSession, user_id: int, document_id: int) -> bool:
    document = await get_document(db, user_id, document_id)
    if document is None:
        return False
    if document.file_type == "csv":
        await asyncio.to_thread(_drop_table, f"csv_doc_{document.id}")
    else:
        await asyncio.to_thread(_delete_pdf_fts, document.id)
    try:
        (_uploads_root() / document.storage_key).unlink(missing_ok=True)
    except OSError as exc:  # pragma: no cover - non-fatal cleanup warning
        logger.warning("Could not remove uploaded file %s: %s", document.storage_key, exc)
    await db.delete(document)
    await db.commit()
    return True


async def attach_documents(
    db: AsyncSession, user_id: int, session_id: int, document_ids: list[int]
) -> list[ChatDocument]:
    if not document_ids:
        return []
    if len(set(document_ids)) > MAX_ATTACHMENTS_PER_TURN:
        raise DocumentError(f"Attach at most {MAX_ATTACHMENTS_PER_TURN} documents per message.")

    result = await db.execute(
        select(ChatDocument).where(ChatDocument.user_id == user_id, ChatDocument.id.in_(set(document_ids)))
    )
    documents = list(result.scalars().all())
    if len(documents) != len(set(document_ids)):
        raise DocumentError("One or more attached documents were not found.")

    existing = await db.execute(
        select(ChatDocumentSession.document_id).where(ChatDocumentSession.session_id == session_id)
    )
    attached = set(existing.scalars().all())
    for document in documents:
        if document.id not in attached:
            db.add(ChatDocumentSession(document_id=document.id, session_id=session_id))
    await db.commit()
    return documents


async def session_documents(db: AsyncSession, user_id: int, session_id: int) -> list[ChatDocument]:
    result = await db.execute(
        select(ChatDocument)
        .join(ChatDocumentSession, ChatDocumentSession.document_id == ChatDocument.id)
        .where(ChatDocumentSession.session_id == session_id, ChatDocument.user_id == user_id)
        .order_by(ChatDocument.created_at.asc())
    )
    return list(result.scalars().all())


async def build_document_context(
    db: AsyncSession, user_id: int, document_ids: list[int]
) -> str:
    if not document_ids:
        return ""
    result = await db.execute(
        select(ChatDocument)
        .options(selectinload(ChatDocument.pages))
        .where(ChatDocument.user_id == user_id, ChatDocument.id.in_(set(document_ids)))
    )
    documents = list(result.scalars().all())
    if not documents:
        return ""

    blocks: list[str] = []
    csv_index = 1
    for document in documents:
        summary = json.loads(document.summary_json or "{}")
        if document.file_type == "csv":
            columns = ", ".join(
                f"{col.get('sqlite_name')} ({col.get('dtype')}, nulls={col.get('null_count')})"
                for col in summary.get("columns", [])
            )
            blocks.append(
                f"[ATTACHED CSV #{csv_index}] document_id={document.id} filename={document.filename} "
                f"table=csv_doc_{document.id} rows={document.row_count}\n"
                f"Columns: {columns}\n"
                f"Sample rows (JSON): {json.dumps(summary.get('sample_rows', []))}"
            )
            csv_index += 1
            continue

        if document.needs_ocr:
            blocks.append(
                f"[ATTACHED PDF] document_id={document.id} filename={document.filename} pages={document.page_count}\n"
                "No extractable text layer was detected. Tell the user this PDF appears to be scanned and cannot be read without OCR."
            )
            continue

        if document.is_inlineable:
            inline_text = "\n\n".join(
                f"[page {page.page_number}]\n{page.content}" for page in document.pages
            )[:PDF_INLINE_MAX_CHARS]
            blocks.append(
                f"[ATTACHED PDF] document_id={document.id} filename={document.filename} pages={document.page_count}\n{inline_text}"
            )
        else:
            outline = summary.get("outline", [])
            outline_text = "\n".join(
                f"{'  ' * int(node.get('depth', 0))}- {node.get('title')} (page {node.get('page_number') or '?'})"
                for node in outline[:40]
            )
            blocks.append(
                f"[ATTACHED PDF] document_id={document.id} filename={document.filename} pages={document.page_count}\n"
                f"Outline:\n{outline_text or '(no bookmarks)'}\n"
                "Use search_pdf and read_pdf_pages to inspect relevant sections."
            )
    return "\n\n".join(blocks)


def _fts_match_query(query: str) -> str:
    terms = re.findall(r"[0-9A-Za-z_]{2,}", query or "")
    if not terms:
        raise DocumentError("Search query must contain at least two alphanumeric characters.")
    return " OR ".join(f'"{term}"' for term in terms[:8])


def query_csv_sync(table_name: str, sql_query: str) -> dict[str, Any]:
    if not re.fullmatch(r"csv_doc_\d+", table_name):
        raise DocumentError("Invalid CSV table name.")
    if not sql_query or not sql_query.strip():
        raise DocumentError("SQL query is required.")

    conn = _connect_sync()
    try:
        conn.execute("PRAGMA query_only=ON")

        def authorizer(action: int, arg1: Any, arg2: Any, dbname: Any, source: Any) -> int:
            if action == sqlite3.SQLITE_SELECT:
                return sqlite3.SQLITE_OK
            if action == sqlite3.SQLITE_READ:
                return sqlite3.SQLITE_OK if arg1 == table_name else sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_FUNCTION:
                return sqlite3.SQLITE_OK
            return sqlite3.SQLITE_DENY

        conn.set_authorizer(authorizer)
        cursor = conn.execute(sql_query)
        rows = cursor.fetchmany(MAX_CSV_QUERY_ROWS + 1)
        truncated = len(rows) > MAX_CSV_QUERY_ROWS
        rows = rows[:MAX_CSV_QUERY_ROWS]
        columns = [description[0] for description in cursor.description or []]
        return {
            "table": table_name,
            "columns": columns,
            "row_count": len(rows),
            "truncated": truncated,
            "rows": [dict(row) for row in rows],
        }
    except sqlite3.DatabaseError as exc:
        raise DocumentError(f"SQL query rejected: {exc}") from exc
    finally:
        conn.close()


def describe_csv_sync(table_name: str, column: str | None = None) -> dict[str, Any]:
    if not re.fullmatch(r"csv_doc_\d+", table_name):
        raise DocumentError("Invalid CSV table name.")
    conn = _connect_sync()
    try:
        conn.execute("PRAGMA query_only=ON")
        quoted = f'"{column}"' if column and re.fullmatch(r"[0-9A-Za-z_]+", column) else None
        if column and quoted is None:
            raise DocumentError("Column name contains unsupported characters.")
        if quoted:
            total = conn.execute(f'SELECT COUNT(*), COUNT({quoted}) FROM "{table_name}"').fetchone()
            numeric = conn.execute(f'SELECT AVG({quoted}), MIN({quoted}), MAX({quoted}) FROM "{table_name}" WHERE typeof({quoted}) IN (\'integer\', \'real\')').fetchone()
            top = conn.execute(f'SELECT {quoted} AS value, COUNT(*) AS count FROM "{table_name}" GROUP BY {quoted} ORDER BY count DESC LIMIT 10').fetchall()
            return {
                "table": table_name,
                "column": column,
                "row_count": total[0] if total else 0,
                "non_null_count": total[1] if total else 0,
                "average": numeric[0] if numeric else None,
                "min": numeric[1] if numeric else None,
                "max": numeric[2] if numeric else None,
                "top_values": [dict(row) for row in top],
            }
        columns = conn.execute(f'PRAGMA table_info("{table_name}")').fetchall()
        return {
            "table": table_name,
            "columns": [{"name": row["name"], "type": row["type"]} for row in columns],
            "row_count": conn.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0],
        }
    except sqlite3.DatabaseError as exc:
        raise DocumentError(f"Could not describe CSV: {exc}") from exc
    finally:
        conn.close()


def search_pdf_sync(document_id: int, query: str, top_k: int = 5) -> list[dict[str, Any]]:
    match_query = _fts_match_query(query)
    limit = max(1, min(int(top_k), 10))
    conn = _connect_sync()
    try:
        rows = conn.execute(
            "SELECT page_number, snippet(pdf_pages_fts, 2, '<<', '>>', '...', 12) AS snippet, "
            "bm25(pdf_pages_fts) AS score FROM pdf_pages_fts "
            "WHERE pdf_pages_fts MATCH ? AND document_id = ? ORDER BY score LIMIT ?",
            (match_query, document_id, limit),
        ).fetchall()
        return [{"page_number": row["page_number"], "snippet": row["snippet"], "score": row["score"]} for row in rows]
    except sqlite3.DatabaseError as exc:
        raise DocumentError(f"PDF search failed: {exc}") from exc
    finally:
        conn.close()


def read_pdf_pages_sync(document_id: int, start_page: int, end_page: int | None = None) -> dict[str, Any]:
    start = max(1, int(start_page))
    end = int(end_page) if end_page is not None else start
    end = max(start, min(end, start + MAX_PDF_PAGES_PER_READ - 1))
    conn = _connect_sync()
    try:
        rows = conn.execute(
            "SELECT page_number, content FROM chat_document_pages "
            "WHERE document_id = ? AND page_number BETWEEN ? AND ? ORDER BY page_number",
            (document_id, start, end),
        ).fetchall()
    finally:
        conn.close()
    pages = [{"page_number": row["page_number"], "content": row["content"]} for row in rows]
    combined = "\n\n".join(f"[page {page['page_number']}]\n{page['content']}" for page in pages)
    if len(combined) > MAX_PDF_READ_CHARS:
        combined = combined[:MAX_PDF_READ_CHARS] + "\n\n[truncated]"
    return {"document_id": document_id, "start_page": start, "end_page": end, "pages": combined}
