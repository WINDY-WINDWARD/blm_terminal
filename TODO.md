# Desktop Conversion TODO

## Phase 1: Frontend Preparation & Multi-Window State
- [ ] Extract global connection hooks into `<GlobalAppProviders>` component.
- [ ] Create isolated widget route `src/app/widget/[widgetType]/page.tsx` and layout.
- [ ] Add "Pop-out" button to `Panel.tsx` with URL state serialization.
- [ ] Add runtime API key settings UI and update OpenAlgo/Python to read dynamically.

## Phase 2: Backend Packaging (Python)
- [ ] Remove/Deprecate MCP integration (`run_mcp_stdio.py`).
- [ ] Update `backend/main.py` and `backend/app/config.py` for OS-safe `LOG_DIR` and `DB_PATH`.
- [ ] Create PyInstaller build script `scripts/build_backend.ps1` with hidden imports and `--add-data`.

## Phase 3: Electron Orchestrator Setup
- [ ] Install Electron dependencies (`electron`, `electron-builder`, `get-port`).
- [ ] Create `electron/main.js`.
- [ ] Implement dynamic port allocation for Next.js and Python.
- [ ] Implement child process spawning for Next.js and backend.
- [ ] Implement `window.open` interception for multi-window support.
- [ ] Implement clean teardown on application quit.

## Phase 4: Build & Distribution
- [ ] Configure `electron-builder` to package `.next`, `server.js`, `public`, and `node_modules`.
- [ ] Add `asarUnpack` for `sharp`.
- [ ] Add `build:desktop` orchestration script to `package.json`.