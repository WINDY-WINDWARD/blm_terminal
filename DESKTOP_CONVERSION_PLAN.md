# BLM Terminal: Desktop Conversion Plan

## Goal
Fully convert the BLM Terminal (Next.js 16 Custom Server + FastAPI Python backend) into a native, install-anywhere, multi-window desktop client. 
**Constraints:** Minimal code changes, full feature parity, NO mockups, NO MVPs, NO hacky workarounds.

## Architecture Stack
* **Desktop Framework:** Electron (used as an orchestrator and multi-window manager)
* **Frontend Runtime:** Node.js (via Electron) running the existing custom Next.js `server.js`
* **Backend Runtime:** PyInstaller compiled standalone executable (`blm-backend.exe`)
* **Packager:** `electron-builder`

---

## Phase 1: Frontend Preparation & Multi-Window State (Next.js & Jotai)

### 1. Global Provider Refactor
Extract the essential global connection hooks (e.g., `marketDataService.connect()`, OpenAlgo checks) from `TerminalContainer.tsx` into a new shared `<GlobalAppProviders>` component. This ensures popped-out widgets maintain live WebSocket feeds.

### 2. Isolated Widget Route
Create `src/app/widget/[widgetType]/page.tsx` with an empty layout to render specific widgets (e.g., `<ChartWidget />`) at 100vw/100vh, bypassing the grid system entirely.

### 3. Pop-out UI & State Serialization
Add a "Pop-out" button to `Panel.tsx`. Because popped-out OS windows receive an empty `sessionStorage`, the button will serialize necessary layout states (like `activeWatchlistId` or `moversCategory`) into URL query parameters (e.g., `/widget/WATCH?watchlistId=3`). The widget route will parse these to rehydrate local Jotai state, while `localStorage`-backed atoms (like `activeSymbolAtom`) will sync automatically.

### 4. Runtime API Key Settings
Create a UI Settings panel to input OpenAlgo and AI API keys. Update `src/lib/openalgo-server.ts` and the Python backend to read these from the local SQLite `system_config` table (or Electron's `userData`) instead of relying on build-time/startup `.env` variables.

---

## Phase 2: Backend Packaging & OS-Safe Paths (Python)

### 1. Deprecate MCP
Drop support for `run_mcp_stdio.py` and the `/api/mcp` endpoints. They will not be exposed or hooked into the desktop bundle.

### 2. OS-Safe Logging & Database
Modify `backend/main.py` and `backend/app/config.py`. Replace hardcoded `__file__.parent` logging and local `./data.db` paths with dynamic OS-safe paths (e.g., `%APPDATA%\blm_terminal`) driven by `LOG_DIR` and `DB_PATH` environment variables passed by Electron.

### 3. PyInstaller Compilation
Create `scripts/build_backend.ps1` to compile the FastAPI server into a single executable (`blm-backend.exe`). Configure hidden imports for `aiosqlite` and `rookiepy`, and explicitly include `alembic/` and `alembic.ini` using `--add-data` flags so database migrations execute cleanly post-compilation.

---

## Phase 3: Electron Orchestrator Setup (`electron/main.js`)

### 1. Dynamic Port Allocation
Use a library like `get-port` on startup to dynamically assign free ports (`NEXT_PORT` and `PYTHON_PORT`), preventing collisions with other desktop software.

### 2. Sidecar Spawning
* **Backend:** Spawn `blm-backend.exe` as a child process with the `PYTHON_PORT`, `DB_PATH`, and `LOG_DIR` environment variables.
* **Frontend:** Spawn the *existing* custom `server.js` using Electron's built-in Node runtime (`child_process.fork`), passing `PORT=NEXT_PORT` and `PYTHON_BACKEND_URL=http://127.0.0.1:<PYTHON_PORT>`.

### 3. Native Multi-Window Interception
Intercept `window.open()` calls using `webContents.setWindowOpenHandler` in the Electron main process. When the frontend requests a pop-out, Electron will cancel the default browser behavior and programmatically generate a new native `BrowserWindow` pointing to the widget's local URL.

### 4. Clean Teardown
Bind the Next.js and Python background processes to Electron's `app.on('quit')` event to ensure all servers are cleanly killed when the user closes the terminal.

---

## Phase 4: Build & Distribution Pipeline (electron-builder)

### 1. Preserve Custom WebSocket Handler
We will **NOT** use Next.js `output: "standalone"`, as it generates a generic server that ignores the custom `/ws/market` handler inside `server.js`. 

### 2. Packaging Config
Configure `electron-builder` to package the raw `.next` folder, your custom `server.js`, `server/`, `public/`, and the required production `node_modules` into the `.asar` archive.

### 3. Native Dependency Extraction
Add `asarUnpack: ["**/node_modules/sharp/**/*"]` to the `electron-builder` configuration so Next.js's native image optimization binaries can be loaded and executed by the OS from within the ASAR wrapper.

### 4. Build Orchestration Script
Add a `"build:desktop"` script to `package.json` that sequentially runs: Next.js build -> PyInstaller compilation -> electron-builder packaging.
