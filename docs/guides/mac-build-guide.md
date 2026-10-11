# macOS Build & Installation Guide

This guide explains how to build, package, and install BLM Terminal natively on macOS (Apple Silicon `arm64` or Intel `x64`).

---

## Prerequisites

1. **Node.js**: v20+ and `npm`
2. **Python**: Python 3.11+ (available as `python3`)
3. **Xcode Command Line Tools**: Required by PyInstaller and `electron-builder` for Mach-O binary packaging (`xcode-select --install`)

---

## Step 1: Install Frontend & Electron Dependencies

From the repository root:

```bash
npm install
```

Ensure `electron/licenseConfig.js` exists (if not, copy from root `licenseConfig.js` or run `npm run gen:license-config`):
```bash
[ -f electron/licenseConfig.js ] || cp licenseConfig.js electron/licenseConfig.js
```

---

## Step 2: Set Up the Python Backend Virtual Environment

Create and populate the virtual environment inside `backend/.venv`. The backend build script (`scripts/build_backend.sh`) automatically detects and uses this environment.

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pip install pyinstaller "camoufox==0.5.6"
deactivate
cd ..
```

---

## Step 3: Build the macOS Desktop Application

Run the full macOS desktop build command from the repository root:

```bash
npm run build:desktop:mac
```

### What this command does:
1. **`npm run build:next`**: Compiles the production Next.js application into `.next/`.
2. **`npm run build:backend:mac`**: Executes `scripts/build_backend.sh`, which runs PyInstaller to freeze `backend/main.py` along with Alembic migrations, static assets, and `camoufox` browser dependencies into a single standalone Mach-O executable at `backend/dist/blm-backend`.
3. **`electron-builder --mac --config electron-builder.json`**: Packages the Next.js server, Electron main process, and `backend/dist/blm-backend` (bundled under `Contents/Resources/blm-backend/blm-backend`) into a `.app` bundle and a distributable `.dmg` disk image inside `dist-desktop/`.

If you only want to produce an unpacked `.app` bundle in `dist-desktop/mac-arm64/` for quick local testing without waiting for DMG compression:

```bash
npm run pack:desktop:mac
```

---

## Step 4: Install on Your Mac

### Option A: Via the `.dmg` Installer
1. Open the generated `.dmg` file in `dist-desktop/` (e.g., `dist-desktop/BLM Terminal-<version>-arm64.dmg`).
2. Drag **BLM Terminal.app** into the **Applications** folder.

### Option B: Direct CLI Copy to `/Applications`
```bash
rm -rf "/Applications/BLM Terminal.app"
cp -R "dist-desktop/mac-arm64/BLM Terminal.app" "/Applications/BLM Terminal.app"
xattr -cr "/Applications/BLM Terminal.app"
```
*(Note: `xattr -cr` clears macOS Gatekeeper quarantine attributes on unsigned local builds so the app launches without a "developer cannot be verified" prompt).*

---

## Runtime Paths on macOS

When running the installed production `.app` on macOS:
- **Application Support / User Data**: `~/Library/Application Support/blm_terminal/`
- **SQLite Database**: `~/Library/Application Support/blm_terminal/data.db`
- **Electron Logs**: `~/Library/Application Support/blm_terminal/logs/electron.log`
- **Backend Logs**: `~/Library/Application Support/blm_terminal/logs/`
- **Playwright / Camoufox Cache**: `~/Library/Caches/ms-playwright/`
