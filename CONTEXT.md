# Desktop Conversion Context

## Architectural Decisions & Constraints

- **No Next.js Standalone Export**: `output: "standalone"` cannot be used because it generates a generic server that ignores the custom `server.js` housing the critical `/ws/market` in-process handler. We must package the raw `.next` output and run the custom `server.js` directly via Electron's Node.js runtime.
- **OS-Safe Paths for PyInstaller**: The Python backend natively writes logs to `Path(__file__).parent / "logs"`. Inside a compiled PyInstaller `.exe`, this resolves to an ephemeral `_MEIPASS` directory. We must use OS-safe paths (e.g., `%APPDATA%`) injected via environment variables (`LOG_DIR`, `DB_PATH`) to prevent crashes or data loss.
- **Jotai SessionStorage Limitations**: Popped-out widgets open in new OS windows, which do not inherit `sessionStorage` (used heavily via `tabStorage` for isolated layouts). To maintain context (like active watchlist), the pop-out button must serialize this state into URL query parameters to rehydrate the Jotai store on mount.
- **Native Dependencies (`sharp`)**: Next.js image optimization relies on `sharp`. Native `.node` binaries cannot execute within an Electron `.asar` wrapper. We must explicitly unpack them using `asarUnpack`.
- **MCP Hook Deprecation**: Bundling the FastAPI backend in PyInstaller effectively hides its standard I/O streams from external processes (like Claude Desktop). Implementing a bypass just for MCP adds unnecessary complexity to the Electron desktop bundle, so we opted to deprecate `run_mcp_stdio.py`.