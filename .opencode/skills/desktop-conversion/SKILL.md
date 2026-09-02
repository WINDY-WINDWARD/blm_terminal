# Skill: BLM Desktop Conversion
**Description**: Strict technical guidelines for converting the BLM Terminal to a multi-window Electron desktop application.

## 🚨 MANDATES & CONSTRAINTS 🚨
1. **NO HACKY CHANGES**: Follow the architecture precisely. No mockups, no MVPs, no "let's fix it later". Full feature parity is required.
2. **FOLLOW THE PLAN**: You MUST adhere to the steps outlined in `/DESKTOP_CONVERSION_PLAN.md` located at the root of the project.
3. **PRESERVE NEXT.JS API**: DO NOT attempt to rewrite the Next.js `/api/...` routes into Rust, Python, or another framework. The Next.js custom `server.js` MUST be maintained and utilized.
4. **NO STANDALONE EXPORT**: DO NOT use Next.js `output: "standalone"`. It ignores the custom `server.js` (which houses the critical `/ws/market` handler). You must package the raw `.next` and `node_modules` folders.

## Technology Stack & Execution Details

### 1. Electron Orchestrator (`electron/main.js`)
* **Spawning Servers**: Electron must spawn two child processes:
  * Next.js: Run `server.js` using `child_process.fork()` natively via Electron's Node runtime.
  * Python: Run `blm-backend.exe` using `child_process.spawn()`.
* **Port Assignment**: Use `get-port` to dynamically assign `NEXT_PORT` and `PYTHON_PORT`. Pass these as environment variables (`PORT`, `PYTHON_BACKEND_URL`).
* **Multi-Window Support**: Intercept `webContents.setWindowOpenHandler` in the Electron main process. When `window.open` is called by the frontend, spawn a new `BrowserWindow` loading the target local URL.
* **Teardown**: Ensure child processes are killed on `app.on('quit')`.

### 2. Frontend Changes (Next.js & Jotai)
* **Isolated Routes**: Create `/widget/[widgetType]/page.tsx` with an empty layout to render isolated widgets for popped-out windows.
* **Global Providers**: Extract global connection hooks (e.g., `marketDataService.connect()`) from `TerminalContainer.tsx` into a `<GlobalAppProviders>` component so popped-out windows receive live data.
* **State Serialization**: The Pop-out button in `Panel.tsx` MUST serialize `sessionStorage`-backed Jotai atoms (like `activeWatchlistId`) into URL query parameters (e.g. `?watchlistId=3`), as new OS windows receive an empty `sessionStorage`.
* **API Keys**: Convert OpenAlgo and AI API Keys from `.env` dependencies to runtime configurations stored in the SQLite `system_config` table (or Electron `userData`), manageable via a UI settings panel.

### 3. Backend Packaging (PyInstaller)
* **Command**: `pyinstaller --name blm-backend --onefile backend/main.py --add-data "backend/alembic:alembic" --add-data "backend/alembic.ini:."`
* **OS-Safe Paths**: Modify `backend/main.py` and `backend/app/config.py` to accept `LOG_DIR` and `DB_PATH` from environment variables. Do NOT write to `Path(__file__).parent / "logs"` as it points to `sys._MEIPASS` inside a PyInstaller bundle and will fail or delete logs.
* **Hidden Imports**: Ensure `aiosqlite`, `rookiepy`, and SQLite SQLAlchemy dialects are included.
* **Deprecation**: Completely ignore and drop support for `run_mcp_stdio.py`.

### 4. Distribution (`electron-builder`)
* Configure `electron-builder.json` or the `"build"` block in `package.json` to include:
  * `.next/`
  * `server.js` and `server/`
  * `public/`
  * The compiled `blm-backend.exe`
* **CRITICAL**: Include `asarUnpack: ["**/node_modules/sharp/**/*"]` so Next.js's native image optimization binaries execute correctly under the ASAR archive. 

## Workflow & Documentation Tracking
Whenever invoked to begin or continue the desktop conversion, you MUST maintain three specific tracking documents in the project root to keep the user up-to-date. If they do not exist, create them immediately.

You MUST continuously update these documents during execution in the following exact order:
1. **`TODO.md`**: Update this FIRST. Track the overall progress, mapping out the phases from the conversion plan. Clearly mark what is pending, what is currently in progress, and what is complete.
2. **`MEMORY.md`**: Update this SECOND. Track *what* has been done and *how* it was executed (e.g., specific file modifications, commands run, configurations applied, libraries added).
3. **`CONTEXT.md`**: Update this THIRD. Track *why* a specific technical approach was taken, documenting architectural decisions, constraints, limitations, and considerations that influenced the implementation (e.g., why Next.js standalone mode was bypassed).

After updating the tracking docs, read `DESKTOP_CONVERSION_PLAN.md`, verify current progress against `TODO.md`, and execute the next logical phase strictly adhering to the technical rules defined above.