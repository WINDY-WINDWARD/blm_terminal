# Desktop Conversion Memory

## Initialization
- Transitioned to Build Mode.
- Created `DESKTOP_CONVERSION_PLAN.md` to outline the 4-phase conversion architecture.
- Created `.opencode/skills/desktop-conversion/SKILL.md` to define strict technical constraints and workflow for agents.
- Updated the Skill file to mandate continuous updates to `TODO.md`, `MEMORY.md`, and `CONTEXT.md` in that specific order.
- Initialized `TODO.md`, `MEMORY.md`, and `CONTEXT.md` to track progress and document decisions.

## Execution Log
- Overwrote `TODO.md` to insert "Phase 0" for code review fixes and updated Phase 1 & 2 to include dynamic model fetching and OAuth FastAPI migration.
- Executed Phase 0 fixes: added `Accept: text/event-stream` to `AiWidget.tsx`, expanded SSE proxy timeout to 10 minutes in `route.ts`, and refactored `ai_summarizer.py` to asynchronously fetch `ai.api_key` from `system_config`.
- Executed Phase 1: created `<GlobalAppProviders>`, implemented pop-out widget route `src/app/widget/[widgetType]/page.tsx`, and built the new dynamic `SettingsWidget.tsx` with Zen/Go model fetching.
- Executed Phase 2: moved Gemini login from CLI script to FastAPI router `gemini_auth.py`, removed MCP server, and added OS-safe PyInstaller compilation script `build_backend.ps1`.
- Executed Phase 3 & 4: wrote `electron/main.js` with `net.createServer` port scanning and `child_process.fork/spawn`, configured `package.json` for `electron-builder` with ASAR unpacking for `sharp`. All tasks complete.
- Executed Phase 5 (AI chat document uploads): Alembic migration `j88888888888_add_chat_documents.py`; new `backend/app/services/document_service.py`; six document endpoints in `backend/app/routers/ai_chat.py`; five tools wired into `backend/app/mcp_server.py` and `backend/app/services/ai_chat_service.py`; binary-safe multipart proxying in `src/app/api/py/[...path]/route.ts`; attachment tray, drag-and-drop and library panel in `src/components/widgets/AiWidget.tsx`.
- Added frontend test seams: `isSupportedDocument`, `filterSupportedDocuments`, `addAttachedDocument`, `removeAttachedDocument`, `formatBytes`, `SUPPORTED_DOCUMENT_EXTENSIONS` and `MAX_ATTACHMENTS_PER_TURN` are now exported from `AiWidget.tsx` and unit-tested in `src/__tests__/widgets/aiDocuments.test.ts`; multipart byte-preservation is covered by `src/__tests__/api/py-proxy/route.test.ts`.
- Backend verification: `tests/test_document_service.py` (16 passed) and `tests/test_ai_documents.py` (30 passed) run with `-p no:cacheprovider -p no:tmpdir`; `alembic upgrade head` and `downgrade i77777777777` round-tripped against throwaway DBs; `tsc --noEmit` clean.
- Packaging: added `--hidden-import "python_multipart"` and `--collect-all "pypdf"` to `scripts/build_backend.ps1` and `scripts/build_backend.sh`. `pypdf` is imported lazily inside `_ingest_pdf_sync`, and the new upload route is the backend's first `File(...)` parameter (so `python_multipart` resolves at route-definition time).
- Hardened two behaviours found while testing: password-protected PDFs now return the friendly "password protected" error (pypdf's `decrypt("")` returns 0 instead of raising), and the scanned-PDF heuristic was retuned from `max(40, page_count * 20)` to `max(10, page_count * 10)` so short text-layer PDFs are no longer misreported as needing OCR.
- Verification completed once the sandbox was lifted: installed `pypdf` 6.21.0 into `backend/.venv`, re-ran the document tests with no PYTHONPATH shim (46 passed), and ran the frontend suite through vitest (13 passed across `src/__tests__/api/py-proxy/route.test.ts` and `src/__tests__/widgets/aiDocuments.test.ts`).
- Regression baseline comparison against the untouched `feat/desktop-conversion` checkout: backend failure/error sets are identical (169 items each) with +46 new passing tests, and the frontend failure set is identical (8 pre-existing `DealsWidget` / `PosWidget` timeouts). `feat/pdf-csv-uploads` sits on `9bbb38b2`, one commit behind `457440a9` (TradingView watchlist import), which is what accounts for the 16 backend and 14 frontend tests only the untouched checkout collects.
