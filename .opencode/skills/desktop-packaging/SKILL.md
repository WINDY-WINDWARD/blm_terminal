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

5. **Packaging Architecture Rules**:
   - `electron-builder.json` is the single source of truth (do not duplicate configurations into `package.json`).
   - `asar: true` must be kept with `asarUnpack: ["**/node_modules/sharp/**/*", "**/node_modules/@img/**/*"]`.
   - In `electron/main.js`, Next.js must be passed `NEXT_DIR` pointing to the ASAR archive (`path.join(process.resourcesPath, 'app.asar')`) so server components resolve internal modules cleanly.
   - Dynamic port allocation is performed via `findFreePort()` in `electron/main.js` for both Python and Next.js.
   - Child processes spawned by Electron must use `windowsHide: true`.
