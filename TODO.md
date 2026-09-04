# Desktop Conversion TODO

## Phase 0: Code Review Fixes & Architecture Tweaks
- [x] Fix AI Chat Stream Timeout (`src/app/api/py/[...path]/route.ts` and `AiWidget.tsx`).
- [x] Fix AI Summarizer to read `ai.api_key` dynamically from SQLite `system_config`.

## Phase 1: Frontend Preparation & Multi-Window State
- [x] Extract global connection hooks into `<GlobalAppProviders>` component.
- [x] Create isolated widget route `src/app/widget/[widgetType]/page.tsx` and layout.
- [x] Add "Pop-out" button to `Panel.tsx` with URL state serialization.
- [x] Add runtime API key settings UI (Zen/Go/Gemini) and dynamic Hunter/Verifier model dropdowns (`SettingsWidget.tsx`).
- [x] Implement FastAPI backend route `/api/py/ai/provider-models` to dynamically fetch Zen/Go models.

## Phase 2: Backend Packaging (Python)
- [x] Migrate Gemini (Antigravity) OAuth flow from CLI (`ag_login.py`) to FastAPI routes (`/api/auth/gemini/*`).
- [x] Store `.ag_credentials.json` in an OS-safe `userData` directory.
- [x] Remove/Deprecate MCP integration (`run_mcp_stdio.py`).
- [x] Update `backend/main.py` and `backend/app/config.py` for OS-safe `LOG_DIR` and `DB_PATH`.
- [x] Create PyInstaller build script `scripts/build_backend.ps1` with hidden imports and `--add-data`.

## Phase 3: Electron Orchestrator Setup
- [x] Install Electron dependencies (`electron`, `electron-builder`, `get-port`).
- [x] Create `electron/main.js`.
- [x] Implement dynamic port allocation for Next.js and Python.
- [x] Implement child process spawning for Next.js and backend.
- [x] Implement `window.open` interception for multi-window support.
- [x] Implement clean teardown on application quit.

## Phase 4: Build & Distribution
- [x] Configure `electron-builder` to package `.next`, `server.js`, `public`, and `node_modules`.
- [x] Add `asarUnpack` for `sharp`.
- [x] Add `build:desktop` orchestration script to `package.json`.