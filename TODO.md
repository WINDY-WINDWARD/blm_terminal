# Desktop Conversion TODO

## Phase 1: Frontend Preparation & Multi-Window State
- [x] Create branch `feat/desktop-conversion` and initialize tracking docs.
- [x] Extract global connection hooks into `<GlobalAppProviders>` component.
- [x] Create isolated widget route `src/app/widget/[widgetType]/page.tsx` and layout.
- [x] Add "Pop-out" button to `Panel.tsx` with URL state serialization.
- [x] Add runtime API key settings UI and update OpenAlgo/Python to read dynamically.

## Phase 2: Backend Packaging (Python)
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

## Phase 5: Resilience, Release System & Upgrades
- [x] Fix AUTHENTICATING hang in `LoginModal.tsx`, Next.js `/api/py/[...path]` proxy, and `electron/main.js` (support `NODE_ENV=production` in local Electron run).
- [x] Add `electron:prod` script to run Electron against pre-built Next.js production build.
- [x] Install `electron-updater` and configure auto-updates in `electron/main.js` & `electron-builder.json`.
- [x] Implement `scripts/release.js` with `YYYY.M.B` version string bumping.
- [x] Add `.github/workflows/release.yml` for automated CI/CD releases on tag pushes.
- [x] Document release lifecycle, when to release, and release commands in `RELEASES.md`.
- [x] Verify test and build passes, commit to git branch.
