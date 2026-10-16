"""API-level tests for the AI chat document library (PDF/CSV uploads).

Covers the user-facing endpoints in ``app/routers/ai_chat.py``: upload,
library listing, session attachment, download, deletion, and the
document-attachment path of ``POST /api/ai/chat``.

An isolated throwaway SQLite *file* is used per test (the app lifespan is
bypassed via httpx ASGITransport).  A file-backed database is required
because CSV/PDF ingestion opens its own synchronous ``sqlite3``
connections to ``settings.db_path``.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 - populate Base.metadata
from app.models.system_config import SystemConfig  # noqa: F401 - sync readers query it
from app.auth import get_current_user
from app.config import settings
from app.database import Base, get_db
from app.models.user import User
from main import app

CSV_BYTES = b"name,pe,notes\nALPHA,10,\nBETA,20,cheap\nGAMMA,,n/a\n"


def _scratch_dir() -> Path:
    path = Path(__file__).resolve().parent / "_tmp_documents" / uuid.uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    return path


def _build_pdf(page_texts: list[str]) -> bytes:
    """Return a minimal single-font PDF whose pages each hold one text run."""
    objects: list[bytes] = []
    count = len(page_texts)
    kids = " ".join(f"{4 + index * 2} 0 R" for index in range(count))
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {count} >>".encode())
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for index, page_text in enumerate(page_texts):
        stream = f"BT /F1 12 Tf 72 720 Td ({page_text}) Tj ET".encode()
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {5 + index * 2} 0 R >>".encode()
        )
        objects.append(
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
        )
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(out)


def _pdf_with_outline(page_texts: list[str], items: list[tuple[str, int, int | None]]) -> bytes:
    """Re-write ``page_texts`` as a PDF carrying ``(title, page, depth)`` bookmarks."""
    pypdf = pytest.importorskip("pypdf")
    reader = pypdf.PdfReader(_BytesIO(_build_pdf(page_texts)))
    writer = pypdf.PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    parents: dict[int, object] = {}
    for title, page_number, depth in items:
        parent = parents.get(depth - 1) if depth else None
        node = writer.add_outline_item(title, page_number, parent=parent)
        parents[depth] = node
    buffer = _BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _BytesIO(data: bytes = b""):
    import io

    return io.BytesIO(data)


@pytest.fixture
async def chat_env(monkeypatch):
    import main as main_mod

    monkeypatch.setattr(main_mod, "LAUNCH_TOKEN", "test-token")

    scratch = _scratch_dir()
    db_file = scratch / "chat.db"
    monkeypatch.setattr(settings, "db_path", str(db_file))

    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with session_factory() as session:
        session.add_all(
            [
                User(id=1, username="alice", hashed_password="x", is_admin=False),
                User(id=2, username="bob", hashed_password="x", is_admin=False),
            ]
        )
        await session.commit()

    auth = SimpleNamespace(user_id=1)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    async def override_get_current_user():
        return User(
            id=auth.user_id,
            username=f"user{auth.user_id}",
            hashed_password="x",
            is_admin=False,
        )

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="https://test",
            headers={"x-blm-token": "test-token"},
        ) as client:
            yield SimpleNamespace(
                client=client,
                auth=auth,
                session_factory=session_factory,
                scratch=scratch,
                db_file=db_file,
            )
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)
        await engine.dispose()
        shutil.rmtree(scratch, ignore_errors=True)


async def _upload(env, filename: str, content: bytes, content_type: str, session_id=None):
    data = {"session_id": str(session_id)} if session_id is not None else None
    return await env.client.post(
        "/api/ai/documents/upload",
        files={"file": (filename, content, content_type)},
        data=data,
    )


async def _upload_csv(env, session_id=None):
    response = await _upload(env, "holdings.csv", CSV_BYTES, "text/csv", session_id)
    assert response.status_code == 200, response.text
    return response.json()


async def _table_exists(db_file: Path, name: str) -> bool:
    with sqlite3.connect(db_file) as conn:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
        ).fetchone()
    return row is not None


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


async def test_upload_csv_returns_metadata_and_stores_file(chat_env):
    body = await _upload_csv(chat_env)

    assert body["filename"] == "holdings.csv"
    assert body["file_type"] == "csv"
    assert body["mime_type"] == "text/csv"
    assert body["file_size"] == len(CSV_BYTES)
    assert body["row_count"] == 3
    assert body["page_count"] is None
    assert body["needs_ocr"] is False
    assert body["attached_session_ids"] == []

    column_names = [column["sqlite_name"] for column in body["summary"]["columns"]]
    assert column_names == ["name", "pe", "notes"]
    assert body["summary"]["columns"][1]["null_count"] == 1
    assert len(body["summary"]["sample_rows"]) == 3

    uploads = list((chat_env.scratch / "uploads").rglob("*.csv"))
    assert len(uploads) == 1
    assert uploads[0].read_bytes() == CSV_BYTES
    assert uploads[0].name.startswith(hashlib.sha256(CSV_BYTES).hexdigest())


async def test_upload_detects_tab_delimited_files(chat_env):
    response = await _upload(
        chat_env, "tabs.tsv", b"symbol\tclose\nALPHA\t10\n", "text/tab-separated-values"
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert [column["sqlite_name"] for column in body["summary"]["columns"]] == ["symbol", "close"]


async def test_upload_duplicate_hash_reuses_existing_document(chat_env):
    first = await _upload_csv(chat_env)
    second = await _upload_csv(chat_env)

    assert second["id"] == first["id"]
    library = (await chat_env.client.get("/api/ai/documents")).json()
    assert len(library) == 1
    assert len(list((chat_env.scratch / "uploads").rglob("*.csv"))) == 1


@pytest.mark.parametrize(
    ("filename", "content", "content_type"),
    [
        ("notes.txt", b"plain text", "text/plain"),
        ("book.xlsx", b"PK\x03\x04binary", "application/vnd.ms-excel"),
        ("noextension", b"data", "application/octet-stream"),
    ],
)
async def test_upload_rejects_unsupported_types(chat_env, filename, content, content_type):
    response = await _upload(chat_env, filename, content, content_type)
    assert response.status_code == 400
    assert "Unsupported" in response.json()["detail"]


async def test_upload_rejects_empty_file(chat_env):
    response = await _upload(chat_env, "empty.csv", b"", "text/csv")
    assert response.status_code == 400
    assert "empty" in response.json()["detail"].lower()


async def test_upload_rejects_file_over_size_limit(chat_env, monkeypatch):
    from app.services import document_service

    monkeypatch.setattr(document_service, "MAX_FILE_SIZE", 64)
    response = await _upload(chat_env, "big.csv", b"a,b\n" + b"1,2\n" * 40, "text/csv")
    assert response.status_code == 400
    assert "50 MB" in response.json()["detail"]


async def test_upload_rejects_unknown_session_id(chat_env):
    response = await _upload(chat_env, "holdings.csv", CSV_BYTES, "text/csv", session_id=999)
    assert response.status_code == 404


async def test_upload_can_attach_immediately(chat_env):
    created = await chat_env.client.post(
        "/api/ai/chat", json={"messages": [{"role": "user", "content": "hi"}]}
    )
    assert created.status_code == 200
    session_id = json.loads(_sse_events(created.text)[0])["id"]

    body = await _upload_csv(chat_env, session_id=session_id)
    assert body["attached_session_ids"] == [session_id]


def _sse_events(body: str) -> list[str]:
    return [
        line[len("data: ") :]
        for line in body.splitlines()
        if line.startswith("data: ")
    ]


# ---------------------------------------------------------------------------
# Library, ownership, download, delete
# ---------------------------------------------------------------------------


async def test_library_lists_attached_session_ids(chat_env):
    document = await _upload_csv(chat_env)
    assert (await chat_env.client.get("/api/ai/documents")).json()[0]["attached_session_ids"] == []

    session_id = await _new_session(chat_env)
    attach = await chat_env.client.post(
        "/api/ai/documents/attach",
        json={"session_id": session_id, "document_ids": [document["id"]]},
    )
    assert attach.status_code == 200

    library = (await chat_env.client.get("/api/ai/documents")).json()
    assert library[0]["attached_session_ids"] == [session_id]


async def test_documents_are_scoped_to_the_owner(chat_env):
    document = await _upload_csv(chat_env)

    chat_env.auth.user_id = 2
    assert (await chat_env.client.get("/api/ai/documents")).json() == []
    assert (await chat_env.client.get(f"/api/ai/documents/{document['id']}")).status_code == 404
    assert (
        await chat_env.client.get(f"/api/ai/documents/{document['id']}/file")
    ).status_code == 404
    assert (await chat_env.client.delete(f"/api/ai/documents/{document['id']}")).status_code == 404

    chat_env.auth.user_id = 1
    assert (await chat_env.client.get(f"/api/ai/documents/{document['id']}")).status_code == 200


async def test_download_returns_original_bytes(chat_env):
    document = await _upload_csv(chat_env)
    response = await chat_env.client.get(f"/api/ai/documents/{document['id']}/file")

    assert response.status_code == 200
    assert response.content == CSV_BYTES
    assert "holdings.csv" in response.headers["content-disposition"]


async def test_delete_document_removes_file_table_and_associations(chat_env):
    document = await _upload_csv(chat_env)
    session_id = await _new_session(chat_env)
    await chat_env.client.post(
        "/api/ai/documents/attach",
        json={"session_id": session_id, "document_ids": [document["id"]]},
    )
    assert await _table_exists(chat_env.db_file, f"csv_doc_{document['id']}")

    response = await chat_env.client.delete(f"/api/ai/documents/{document['id']}")

    assert response.status_code == 200
    assert (await chat_env.client.get("/api/ai/documents")).json() == []
    assert not await _table_exists(chat_env.db_file, f"csv_doc_{document['id']}")
    assert list((chat_env.scratch / "uploads").rglob("*.csv")) == []
    detail = (await chat_env.client.get(f"/api/ai/chat/sessions/{session_id}")).json()
    assert detail["documents"] == []


# ---------------------------------------------------------------------------
# Session attachment lifecycle
# ---------------------------------------------------------------------------


async def _new_session(env) -> int:
    response = await env.client.post(
        "/api/ai/chat", json={"messages": [{"role": "user", "content": "seed"}]}
    )
    assert response.status_code == 200, response.text
    return json.loads(_sse_events(response.text)[0])["id"]


async def test_attach_then_session_detail_returns_documents(chat_env):
    document = await _upload_csv(chat_env)
    session_id = await _new_session(chat_env)

    response = await chat_env.client.post(
        "/api/ai/documents/attach",
        json={"session_id": session_id, "document_ids": [document["id"]]},
    )
    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [document["id"]]

    detail = (await chat_env.client.get(f"/api/ai/chat/sessions/{session_id}")).json()
    assert [item["id"] for item in detail["documents"]] == [document["id"]]


async def test_attach_is_idempotent(chat_env):
    document = await _upload_csv(chat_env)
    session_id = await _new_session(chat_env)
    payload = {"session_id": session_id, "document_ids": [document["id"]]}

    await chat_env.client.post("/api/ai/documents/attach", json=payload)
    second = await chat_env.client.post("/api/ai/documents/attach", json=payload)

    assert second.status_code == 200
    assert [item["id"] for item in second.json()] == [document["id"]]


async def test_attach_rejects_more_than_five_documents(chat_env):
    documents = []
    for index in range(6):
        response = await _upload(
            chat_env,
            f"holdings-{index}.csv",
            b"name,pe\n" + f"SYM{index},{index}\n".encode(),
            "text/csv",
        )
        documents.append(response.json()["id"])
    assert len(set(documents)) == 6
    session_id = await _new_session(chat_env)

    response = await chat_env.client.post(
        "/api/ai/documents/attach",
        json={"session_id": session_id, "document_ids": documents},
    )
    assert response.status_code == 400
    assert "at most 5" in response.json()["detail"]

    five = await chat_env.client.post(
        "/api/ai/documents/attach",
        json={"session_id": session_id, "document_ids": documents[:5]},
    )
    assert five.status_code == 200
    assert len(five.json()) == 5


async def test_attach_rejects_unknown_or_foreign_documents(chat_env):
    session_id = await _new_session(chat_env)
    response = await chat_env.client.post(
        "/api/ai/documents/attach", json={"session_id": session_id, "document_ids": [4242]}
    )
    assert response.status_code == 400

    document = await _upload_csv(chat_env)
    chat_env.auth.user_id = 2
    response = await chat_env.client.post(
        "/api/ai/documents/attach",
        json={"session_id": session_id, "document_ids": [document["id"]]},
    )
    assert response.status_code == 404


async def test_attach_rejects_foreign_session(chat_env):
    document = await _upload_csv(chat_env)
    session_id = await _new_session(chat_env)

    chat_env.auth.user_id = 2
    response = await chat_env.client.post(
        "/api/ai/documents/attach",
        json={"session_id": session_id, "document_ids": [document["id"]]},
    )
    assert response.status_code == 404


async def test_session_delete_detaches_but_keeps_document(chat_env):
    document = await _upload_csv(chat_env)
    session_id = await _new_session(chat_env)
    await chat_env.client.post(
        "/api/ai/documents/attach",
        json={"session_id": session_id, "document_ids": [document["id"]]},
    )

    assert (await chat_env.client.delete(f"/api/ai/chat/sessions/{session_id}")).status_code == 200

    library = (await chat_env.client.get("/api/ai/documents")).json()
    assert [item["id"] for item in library] == [document["id"]]
    assert library[0]["attached_session_ids"] == []
    assert await _table_exists(chat_env.db_file, f"csv_doc_{document['id']}")
    assert (await chat_env.client.get(f"/api/ai/documents/{document['id']}/file")).status_code == 200


# ---------------------------------------------------------------------------
# Chat integration
# ---------------------------------------------------------------------------


@pytest.fixture
def captured_agent(monkeypatch):
    """Replace ``run_chat_agent`` with a silent async generator that records kwargs."""
    captured: dict = {}

    async def _fake_run_chat_agent(**kwargs):
        captured.update(kwargs)
        if False:  # pragma: no cover - makes this function an async generator
            yield ""

    monkeypatch.setattr("app.routers.ai_chat.run_chat_agent", _fake_run_chat_agent)
    return captured


async def test_chat_attaches_documents_and_persists_attachments(chat_env, captured_agent):
    document = await _upload_csv(chat_env)

    response = await chat_env.client.post(
        "/api/ai/chat",
        json={
            "messages": [{"role": "user", "content": "summarise the holdings file"}],
            "document_ids": [document["id"]],
        },
    )

    assert response.status_code == 200
    first_event = json.loads(_sse_events(response.text)[0])
    assert first_event["type"] == "session_id"
    session_id = first_event["id"]

    assert captured_agent["user_id"] == 1
    assert f"document_id={document['id']}" in captured_agent["document_context"]
    assert f"csv_doc_{document['id']}" in captured_agent["document_context"]

    detail = (await chat_env.client.get(f"/api/ai/chat/sessions/{session_id}")).json()
    assert [item["id"] for item in detail["documents"]] == [document["id"]]
    user_message = next(message for message in detail["messages"] if message["role"] == "user")
    assert user_message["attachments"] == [document["id"]]


async def test_chat_without_documents_sends_empty_context(chat_env, captured_agent):
    response = await chat_env.client.post(
        "/api/ai/chat", json={"messages": [{"role": "user", "content": "hello"}]}
    )

    assert response.status_code == 200
    assert captured_agent["document_context"] == ""
    session_id = json.loads(_sse_events(response.text)[0])["id"]
    assert (
        await chat_env.client.get(f"/api/ai/chat/sessions/{session_id}")
    ).json()["documents"] == []


async def test_chat_reports_error_for_foreign_document(chat_env, captured_agent):
    document = await _upload_csv(chat_env)

    chat_env.auth.user_id = 2
    response = await chat_env.client.post(
        "/api/ai/chat",
        json={
            "messages": [{"role": "user", "content": "steal it"}],
            "document_ids": [document["id"]],
        },
    )

    assert response.status_code == 200
    events = [json.loads(event) for event in _sse_events(response.text)]
    assert events[0]["type"] == "error"
    assert "not found" in events[0]["message"]
    assert captured_agent == {}


async def test_chat_deduplicates_repeated_document_ids(chat_env, captured_agent):
    document = await _upload_csv(chat_env)

    response = await chat_env.client.post(
        "/api/ai/chat",
        json={
            "messages": [{"role": "user", "content": "again"}],
            "document_ids": [document["id"], document["id"]],
        },
    )

    session_id = json.loads(_sse_events(response.text)[0])["id"]
    detail = (await chat_env.client.get(f"/api/ai/chat/sessions/{session_id}")).json()
    assert [item["id"] for item in detail["documents"]] == [document["id"]]
    user_message = next(message for message in detail["messages"] if message["role"] == "user")
    assert user_message["attachments"] == [document["id"]]


# ---------------------------------------------------------------------------
# PDF ingestion
# ---------------------------------------------------------------------------


async def test_upload_pdf_extracts_text_pages(chat_env):
    pytest.importorskip("pypdf")
    pages = [
        "Management raised operating margin guidance for FY27.",
        "Risk factors include supply chain concentration.",
    ]
    response = await _upload(
        chat_env, "annual-report.pdf", _build_pdf(pages), "application/pdf"
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["file_type"] == "pdf"
    assert body["page_count"] == 2
    assert body["row_count"] is None
    assert body["needs_ocr"] is False
    assert body["is_inlineable"] is True
    assert body["summary"]["total_chars"] == sum(len(page) for page in pages)
    assert body["summary"]["empty_pages"] == []

    with sqlite3.connect(chat_env.db_file) as conn:
        stored = conn.execute(
            "SELECT page_number, content FROM chat_document_pages WHERE document_id = ? "
            "ORDER BY page_number",
            (body["id"],),
        ).fetchall()
    assert [row[0] for row in stored] == [1, 2]
    assert stored[0][1] == pages[0]


async def test_upload_pdf_indexes_pages_for_search(chat_env):
    pytest.importorskip("pypdf")
    from app.services import document_service

    response = await _upload(
        chat_env,
        "quarterly.pdf",
        _build_pdf(
            [
                "Management raised operating margin guidance for FY27.",
                "Revenue declined in the quarter on weak demand.",
            ]
        ),
        "application/pdf",
    )
    document_id = response.json()["id"]

    matches = document_service.search_pdf_sync(document_id, "operating margin guidance", 5)
    assert matches
    assert matches[0]["page_number"] == 1
    assert "margin" in matches[0]["snippet"].lower()

    with pytest.raises(document_service.DocumentError):
        document_service.search_pdf_sync(document_id, "!!", 5)

    pages = document_service.read_pdf_pages_sync(document_id, 1, 2)
    assert "[page 1]" in pages["pages"]
    assert "Revenue declined" in pages["pages"]


async def test_upload_pdf_flattens_outline(chat_env):
    pytest.importorskip("pypdf")
    content = _pdf_with_outline(
        ["Cover page.", "Risk factors and margin detail.", "Appendix data."],
        [("Cover", 0, 0), ("Risk Factors", 1, 1), ("Appendix", 2, 0)],
    )
    response = await _upload(chat_env, "outlined.pdf", content, "application/pdf")
    assert response.status_code == 200, response.text

    outline = response.json()["summary"]["outline"]
    assert outline == [
        {"depth": 0, "title": "Cover", "page_number": 1},
        {"depth": 1, "title": "Risk Factors", "page_number": 2},
        {"depth": 0, "title": "Appendix", "page_number": 3},
    ]


async def test_upload_pdf_without_text_layer_is_flagged_for_ocr(chat_env):
    pytest.importorskip("pypdf")
    response = await _upload(chat_env, "scanned.pdf", _build_pdf([""]), "application/pdf")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["needs_ocr"] is True
    assert body["summary"]["total_chars"] == 0
    assert body["summary"]["empty_pages"] == [1]


async def test_upload_rejects_password_protected_pdf(chat_env):
    pypdf = pytest.importorskip("pypdf")
    reader = pypdf.PdfReader(_BytesIO(_build_pdf(["secret text"])))
    writer = pypdf.PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    writer.encrypt("hunter2")
    buffer = _BytesIO()
    writer.write(buffer)

    response = await _upload(chat_env, "locked.pdf", buffer.getvalue(), "application/pdf")
    assert response.status_code == 400
    assert "password protected" in response.json()["detail"]


async def test_chat_context_inlines_small_pdf_and_outlines_large_pdf(chat_env):
    pytest.importorskip("pypdf")
    from app.services import document_service

    small = await _upload(
        chat_env, "small.pdf", _build_pdf(["Margin guidance raised."]), "application/pdf"
    )
    large = await _upload(
        chat_env,
        "large.pdf",
        _build_pdf([f"Page {index} body text." for index in range(1, 9)]),
        "application/pdf",
    )

    async with chat_env.session_factory() as session:
        context = await document_service.build_document_context(
            session, 1, [small.json()["id"], large.json()["id"]]
        )

    assert "Margin guidance raised." in context
    assert f"pages={large.json()['page_count']}" in context
    assert "Use search_pdf and read_pdf_pages" in context
