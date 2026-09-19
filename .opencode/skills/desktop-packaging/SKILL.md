# Skill: BLM Desktop Build & Packaging

**Description**: Procedures and guidelines for compiling, packaging, testing, and locally installing the BLM Terminal desktop application from source code.

## Core Directives

1. **Direct From Source Build**:
   - Always compile the fresh source directly using `npm run build:desktop`.
   - Never pull remote pre-compiled release assets when requested to build from source.

2. **Clean State Protocol**:
   - Stop any active background processes before starting a build or install:
     ```powershell
     Get-Process | Where-Object { $_.ProcessName -match "BLM Terminal|blm-backend" } | Stop-Process -Force -ErrorAction SilentlyContinue
     ```
   - Clear temporary build artifacts in `dist-desktop\` to avoid stale cached ASAR or blockmaps:
     ```powershell
     if (Test-Path "dist-desktop") { Remove-Item -Path "dist-desktop\*" -Recurse -Force }
     ```

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

5. **Pre-Release Checklist** (run before every release build):
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
