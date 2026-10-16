"""Focused tests for chat document ingestion and read-only retrieval."""

from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path

import pytest

from app.config import settings
from app.services import document_service


def _work_dir() -> Path:
    path = Path(__file__).resolve().parent / "_tmp_documents" / uuid.uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    return path


def _use_temp_db(monkeypatch) -> str:
    db_path = str(_work_dir() / "documents.db")
    monkeypatch.setattr(settings, "db_path", db_path)
    return db_path


def test_csv_ingest_query_and_sql_guard(monkeypatch):
    _use_temp_db(monkeypatch)

    summary, row_count = document_service._ingest_csv_sync(
        "csv_stage_abc123",
        b"name,pe\nALPHA,10\nBETA,20\n",
    )
    assert row_count == 2
    assert summary["columns"][1]["sqlite_name"] == "pe"

    document_service._rename_table("csv_stage_abc123", "csv_doc_1")

    result = document_service.query_csv_sync(
        "csv_doc_1",
        "SELECT name, pe FROM csv_doc_1 ORDER BY pe DESC",
    )
    assert result["rows"][0]["name"] == "BETA"
    assert result["rows"][1]["pe"] == 10

    description = document_service.describe_csv_sync("csv_doc_1", "pe")
    assert description["average"] == 15
    assert description["min"] == 10
    assert description["max"] == 20

    with pytest.raises(document_service.DocumentError):
        document_service.query_csv_sync("csv_doc_1", "DROP TABLE csv_doc_1")

    with pytest.raises(document_service.DocumentError):
        document_service.query_csv_sync("csv_doc_1", "SELECT * FROM chat_documents")

    with pytest.raises(document_service.DocumentError):
        document_service.query_csv_sync("csv_doc_1", "PRAGMA table_info(csv_doc_1)")


def test_pdf_fts_search_and_page_reads(monkeypatch):
    db_path = _use_temp_db(monkeypatch)
    connection = sqlite3.connect(db_path)
    connection.execute(
        "CREATE TABLE chat_document_pages ("
        "id INTEGER PRIMARY KEY, document_id INTEGER, page_number INTEGER, content TEXT)"
    )
    connection.executemany(
        "INSERT INTO chat_document_pages(document_id, page_number, content) VALUES (?, ?, ?)",
        [
            (7, 1, "Management raised operating margin guidance for FY27."),
            (7, 2, "Revenue declined in the quarter."),
        ],
    )
    connection.commit()
    connection.close()

    document_service._write_pdf_fts(7, [
        "Management raised operating margin guidance for FY27.",
        "Revenue declined in the quarter.",
    ])

    matches = document_service.search_pdf_sync(7, "operating margin guidance", 5)
    assert matches
    assert matches[0]["page_number"] == 1
    assert "operating" in matches[0]["snippet"].lower()
    assert "margin" in matches[0]["snippet"].lower()

    pages = document_service.read_pdf_pages_sync(7, 1, 2)
    assert "[page 1]" in pages["pages"]
    assert "Revenue declined" in pages["pages"]


def test_read_pdf_pages_caps_range(monkeypatch):
    db_path = _use_temp_db(monkeypatch)
    connection = sqlite3.connect(db_path)
    connection.execute(
        "CREATE TABLE chat_document_pages ("
        "id INTEGER PRIMARY KEY, document_id INTEGER, page_number INTEGER, content TEXT)"
    )
    for page in range(1, 11):
        connection.execute(
            "INSERT INTO chat_document_pages(document_id, page_number, content) VALUES (?, ?, ?)",
            (9, page, f"page {page}"),
        )
    connection.commit()
    connection.close()

    result = document_service.read_pdf_pages_sync(9, 1, 99)
    assert result["end_page"] == 5
    assert "page 5" in result["pages"]
    assert "page 6" not in result["pages"]


def _seed_csv_document(monkeypatch, rows: int = 3, table: str = "csv_doc_1") -> str:
    db_path = _use_temp_db(monkeypatch)
    connection = sqlite3.connect(db_path)
    connection.execute(f'CREATE TABLE "{table}" (name TEXT, pe REAL)')
    connection.executemany(
        f'INSERT INTO "{table}" (name, pe) VALUES (?, ?)',
        [(f"SYM{index}", float(index)) for index in range(rows)],
    )
    connection.commit()
    connection.close()
    return table


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT 1; DROP TABLE csv_doc_1",
        "ATTACH DATABASE 'evil.db' AS evil",
        "INSERT INTO csv_doc_1 (name) VALUES ('x')",
        "UPDATE csv_doc_1 SET pe = 0",
        "DELETE FROM csv_doc_1",
        "CREATE TABLE injected (a INTEGER)",
        "DROP TABLE csv_doc_1",
        "PRAGMA table_info(csv_doc_1)",
        "SELECT * FROM chat_documents",
        "SELECT * FROM csv_doc_2",
    ],
)
def test_csv_query_guard_rejects_every_unsafe_statement(monkeypatch, statement):
    table = _seed_csv_document(monkeypatch)

    with pytest.raises(document_service.DocumentError):
        document_service.query_csv_sync(table, statement)

    connection = sqlite3.connect(settings.db_path)
    remaining = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    connection.close()
    assert remaining is not None, "the document table must survive a rejected statement"


def test_csv_query_guard_rejects_unknown_table_name(monkeypatch):
    _use_temp_db(monkeypatch)

    for bad_table in ("chat_documents", "csv_doc_1; DROP TABLE x", "csv_doc_x"):
        with pytest.raises(document_service.DocumentError):
            document_service.query_csv_sync(bad_table, "SELECT 1")


def test_csv_query_caps_rows_and_flags_truncation(monkeypatch):
    table = _seed_csv_document(monkeypatch, rows=document_service.MAX_CSV_QUERY_ROWS + 10)

    result = document_service.query_csv_sync(table, f'SELECT * FROM "{table}"')

    assert result["row_count"] == document_service.MAX_CSV_QUERY_ROWS
    assert result["truncated"] is True
    assert result["columns"] == ["name", "pe"]


def test_csv_query_allows_scoped_select_with_filter_and_aggregate(monkeypatch):
    table = _seed_csv_document(monkeypatch, rows=5)

    filtered = document_service.query_csv_sync(
        table, f'SELECT name FROM "{table}" WHERE pe >= 3 ORDER BY pe DESC'
    )
    assert [row["name"] for row in filtered["rows"]] == ["SYM4", "SYM3"]
    assert filtered["truncated"] is False

    aggregated = document_service.query_csv_sync(
        table, f'SELECT COUNT(*) AS n FROM "{table}"'
    )
    assert aggregated["rows"][0]["n"] == 5

def test_csv_ingest_truncates_oversized_cells_and_caps_columns(monkeypatch):
    _use_temp_db(monkeypatch)

    # 1. Oversized cell value > 200 chars
    long_val = "x" * 350
    csv_bytes = f"col_a,col_b\nval1,{long_val}\n".encode()
    summary, row_count = document_service._ingest_csv_sync("csv_stage_long", csv_bytes)

    assert row_count == 1
    col_b = next(c for c in summary["columns"] if c["name"] == "col_b")
    assert len(col_b["sample_values"][0]) <= document_service.MAX_SUMMARY_VALUE_CHARS + 3
    assert col_b["sample_values"][0].endswith("...")
    assert len(summary["sample_rows"][0]["col_b"]) <= document_service.MAX_SUMMARY_VALUE_CHARS + 3
    assert summary["sample_rows"][0]["col_b"].endswith("...")

    # 2. Columns exceeding MAX_SUMMARY_COLUMNS (100)
    col_headers = [f"c{i}" for i in range(120)]
    row_data = [str(i) for i in range(120)]
    many_cols_csv = (",".join(col_headers) + "\n" + ",".join(row_data) + "\n").encode()
    summary_many, _ = document_service._ingest_csv_sync("csv_stage_many", many_cols_csv)
    assert len(summary_many["columns"]) == document_service.MAX_SUMMARY_COLUMNS


def test_pdf_outline_truncates_long_titles_and_caps_entries():
    # Long title > 200 chars
    long_title = "A" * 300
    dummy_reader = object()
    items = [{"title": long_title}]
    nodes = document_service._flatten_outline(dummy_reader, items)
    assert len(nodes) == 1
    assert len(nodes[0]["title"]) == document_service.MAX_OUTLINE_TITLE_CHARS + 3
    assert nodes[0]["title"].endswith("...")

    # > 200 entries
    many_items = [{"title": f"Section {i}"} for i in range(250)]
    many_nodes = document_service._flatten_outline(dummy_reader, many_items)
    assert len(many_nodes) == document_service.MAX_OUTLINE_ENTRIES


@pytest.mark.asyncio
async def test_build_document_context_truncates_oversized_context():
    from unittest.mock import AsyncMock, MagicMock
    from app.models.ai_chat import ChatDocument

    mock_db = AsyncMock()
    large_summary = {
        "columns": [{"sqlite_name": f"col_{i}", "dtype": "TEXT", "null_count": 0} for i in range(50)],
        "sample_rows": [{"col": "x" * 100} for _ in range(500)],
    }
    mock_doc = MagicMock(spec=ChatDocument)
    mock_doc.id = 1
    mock_doc.filename = "big.csv"
    mock_doc.file_type = "csv"
    mock_doc.row_count = 1000
    mock_doc.summary_json = json.dumps(large_summary)
    mock_doc.pages = []

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_doc]
    mock_db.execute.return_value = mock_result

    context = await document_service.build_document_context(mock_db, user_id=1, document_ids=[1])
    assert len(context) <= document_service.MAX_DOCUMENT_CONTEXT_CHARS + len("\n\n[document context truncated]")
    assert context.endswith("\n\n[document context truncated]")

