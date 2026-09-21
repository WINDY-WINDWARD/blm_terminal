# Skill: BLM Desktop Build & Packaging

**Description**: Procedures and guidelines for compiling, packaging, testing, and locally installing the BLM Terminal desktop application from source code.

## Core Directives

1. **Direct From Source Build**:
   - For local iteration, use the fast build (default): `npm run build:desktop:fast`.
     It runs the Next.js and backend builds concurrently and skips any side
     whose inputs are unchanged (hash state in `dist-desktop/.build-hashes.json`).
   - For releases (version bump, `gh release`, `publish:desktop`), ALWAYS use the
     full sequential build: `npm run build:desktop`. Never ship a fast-build
     installer without re-running the full path first.
   - Never pull remote pre-compiled release assets when requested to build from source.

2. **Clean State Protocol**:
   - Stop any active background processes before starting a build or install:
     ```powershell
     Get-Process | Where-Object { $_.ProcessName -match "BLM Terminal|blm-backend" } | Stop-Process -Force -ErrorAction SilentlyContinue
     ```
   - Full builds only: clear temporary build artifacts in `dist-desktop\` to avoid stale cached ASAR or blockmaps:
     ```powershell
     if (Test-Path "dist-desktop") { Remove-Item -Path "dist-desktop\*" -Recurse -Force }
     ```
   - Fast builds: do NOT clear `dist-desktop\` — the hash-state file and prior
     outputs live there and are what make skipping correct. Staleness is
     prevented by input hashing, not by wiping.

3. **Complete Build Sequence**:
   - Execute the combined desktop build script:
     ```bash
     npm run build:desktop
     ```
   - This executes in sequence:
     1. `npm run build:next` (Turbopack production build + TypeScript verification)
     2. `npm run build:backend` (`./scripts/build_backend.ps1` -> PyInstaller compilation into `backend/dist/blm-backend.exe`)
     3. `electron-builder --win --config electron-builder.json` (Creates the NSIS installer and unpacked binaries in `dist-desktop\`)

4. **Local Silent Uninstallation & Installation**:
   - **Uninstall existing version**:
     ```powershell
     $uninst = "$env:LOCALAPPDATA\Programs\BLM Terminal\Uninstall BLM Terminal.exe"
     if (Test-Path $uninst) {
       $proc = Start-Process -FilePath $uninst -ArgumentList "/S" -PassThru
       $proc.WaitForExit()
     }
     ```
   - **Install freshly built setup executable**:
     ```powershell
     $setup = (Get-ChildItem -Path "dist-desktop" -Filter "BLM Terminal Setup *.exe" | Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName
     $proc = Start-Process -FilePath $setup -ArgumentList "/S" -PassThru
     $proc.WaitForExit()
     ```
   - **Verify the backend actually replaced** (2026-09-22 lesson): stopping
     "BLM Terminal" does NOT stop `blm-backend.exe` children — an orphaned
     backend keeps the installed exe locked, so the installer silently keeps
     the STALE backend while everything else updates. After install, BEFORE
     launching, hash-compare and re-install if mismatched:
     ```powershell
     $a = Get-FileHash "dist-desktop/win-unpacked/resources/blm-backend/blm-backend.exe" -Algorithm SHA256
     $b = Get-FileHash "$env:LOCALAPPDATA\Programs\BLM Terminal\resources\blm-backend\blm-backend.exe" -Algorithm SHA256
     if ($a.Hash -ne $b.Hash) { echo "STALE BACKEND — kill all processes and re-run installer" }
     ```

5. **Pre-Release Checklist** (run before every release build):
    - **Use the FULL build** (`npm run build:desktop`). The fast build skips
      unchanged stages, so it must never produce a shipped installer directly.
    - **Refresh the Codex model list**:
   - **Refresh the Codex model list**: the Codex backend exposes no `/models`
     catalog, so `CODEX_MODELS` in `backend/app/services/codex_auth.py` is
     hand-curated and rots as OpenAI retires IDs. Before each release, check
     the current catalog at `https://developers.openai.com/codex/models` and:
     1. Add newly GA'd model IDs (with plan-tier hints in labels — e.g. Pro-only).
     2. Remove retired IDs (retired models 400 with "model is not supported").
     3. Update `test_codex_request_conversion` in
        `backend/tests/test_multi_provider_offline.py` if the payload shape changed.
     4. Run the offline backend tests (`pytest tests/test_multi_provider_offline.py`).
   - **Scan for other hand-curated provider lists** that may have rotted
     (`_AISTUDIO_RETIRED_PREFIXES`, Zen catalogs, Groq/NVIDIA filters) and
     refresh as needed.

6. **Packaging Architecture Rules**:
   - `electron-builder.json` is the single source of truth (do not duplicate configurations into `package.json`).
   - `asar: true` must be kept with `asarUnpack: ["**/node_modules/sharp/**/*", "**/node_modules/@img/**/*"]`.
   - In `electron/main.js`, Next.js must be passed `NEXT_DIR` pointing to the ASAR archive (`path.join(process.resourcesPath, 'app.asar')`) so server components resolve internal modules cleanly.
   - Dynamic port allocation is performed via `findFreePort()` in `electron/main.js` for both Python and Next.js.
   - Child processes spawned by Electron must use `windowsHide: true`.
