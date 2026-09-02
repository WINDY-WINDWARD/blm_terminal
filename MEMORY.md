# Desktop Conversion Memory

## Initialization
- Transitioned to Build Mode.
- Created `DESKTOP_CONVERSION_PLAN.md` to outline the 4-phase conversion architecture.
- Created `.opencode/skills/desktop-conversion/SKILL.md` to define strict technical constraints and workflow for agents.
- Updated the Skill file to mandate continuous updates to `TODO.md`, `MEMORY.md`, and `CONTEXT.md` in that specific order.
- Initialized `TODO.md`, `MEMORY.md`, and `CONTEXT.md` to track progress and document decisions.
- Created git branch `feat/desktop-conversion` and committed the initialized planning and tracking documents.

## Phase 1: Frontend Preparation & Multi-Window State
- Extracted global connection hooks into `<GlobalAppProviders>` component (`src/components/GlobalAppProviders.tsx`).
- Integrated `<GlobalAppProviders>` into `src/components/Providers.tsx` and cleaned up `src/components/TerminalContainer.tsx`.
- Created isolated widget route `src/app/widget/[widgetType]/page.tsx` and layout `src/app/widget/layout.tsx`.
- Added Pop-out `[POP]` button to `Panel.tsx` with URL state serialization for `symbol`, `watchlistId`, and `category`.
- Updated `backend/app/routers/system_config.py` to support string keys (`openalgo.url`, `openalgo.api_key`, `ai.opencode_zen_api_key`, `ai.api_key`).
- Updated `backend/app/services/llm_provider.py` to read Zen API key from `system_config` if not present in env.
- Updated `src/lib/openalgo-server.ts`, `/api/openalgo/health`, and `/api/openalgo/ws-token` to dynamically load OpenAlgo URL/key from SQLite `system_config`.
- Added API Keys & Runtime Configuration form in `src/components/widgets/SettingsWidget.tsx`.

## Phase 2: Backend Packaging (Python)
- Deprecated MCP stdio runner in `backend/run_mcp_stdio.py`.
- Updated `backend/app/config.py` with `log_dir` setting.
- Updated `backend/main.py` with OS-safe `LOG_DIR` directory creation and PyInstaller `_MEIPASS`-aware `_resolve_alembic_ini()`.
- Created `scripts/build_backend.ps1` to compile FastAPI backend into a single `blm-backend.exe` bundle with Alembic and required hidden imports.

## Phase 3: Electron Orchestrator Setup
- Installed `electron`, `electron-builder`, and `get-port` dev dependencies.
- Implemented `electron/main.js` with:
  - Dynamic port selection for Next.js (port 3000+) and Python (port 4455+).
  - Child process spawning via `fork()` (for custom `server.js`) and `spawn()` (for `blm-backend.exe`).
  - Readiness probing with `waitForHttp`.
  - Multi-window handling with `setWindowOpenHandler` mapping `window.open` requests to native `BrowserWindow`.
  - Safe teardown via `taskkill` (Windows) and `SIGTERM` on process exit.

## Phase 4: Build & Distribution
- Configured `electron-builder.json` packaging `.next`, `server.js`, `server/`, `public/`, and `node_modules`.
- Configured `asarUnpack` for `sharp` and `@img`.
- Added `main: electron/main.js`, `build:next`, `build:backend`, `build:desktop`, and `electron` scripts to `package.json`.
