#!/usr/bin/env bash
set -euo pipefail

echo "Building BLM Backend using PyInstaller (POSIX / macOS / Linux)..."

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="${SCRIPT_DIR}/../backend"

cd "${BACKEND_DIR}"

PYTHON_CMD="python3"
if [ -f ".venv/bin/python" ]; then
    echo "Local virtual environment found at backend/.venv. Using .venv"
    PYTHON_CMD=".venv/bin/python"
elif [ -f ".venv/bin/python3" ]; then
    echo "Local virtual environment found at backend/.venv. Using .venv"
    PYTHON_CMD=".venv/bin/python3"
else
    echo "No local .venv found. Using system python3."
fi

# Ensure PyInstaller is installed
if ! "$PYTHON_CMD" -c "import PyInstaller" &>/dev/null; then
    echo "Installing pyinstaller into the build environment..."
    "$PYTHON_CMD" -m pip install pyinstaller
fi

# Ensure camoufox 0.5.6 is installed
if ! "$PYTHON_CMD" -c "from importlib.metadata import version; assert version('camoufox') == '0.5.6'" &>/dev/null; then
    echo "Installing camoufox==0.5.6 into the build environment..."
    "$PYTHON_CMD" -m pip install "camoufox==0.5.6"
fi

# Clean previous PyInstaller work dirs
rm -rf build dist

# PyInstaller on Unix uses colon (:) as data separator
# On macOS, --onedir avoids expensive cold-boot extraction and syspolicyd scanning
"$PYTHON_CMD" -m PyInstaller \
    --noconfirm \
    --name blm-backend \
    --onedir \
    --add-data "alembic:alembic" \
    --add-data "alembic.ini:." \
    --add-data "app/assets:app/assets" \
    --hidden-import "aiosqlite" \
    --hidden-import "sqlalchemy.dialects.sqlite" \
    --hidden-import "newspaper" \
    --hidden-import "newspaper.extractors" \
    --hidden-import "passlib.handlers.bcrypt" \
    --hidden-import "python_multipart" \
    --collect-all "pypdf" \
    --collect-all "camoufox" \
    --exclude-module "camoufox.gui" \
    --collect-all "apify_fingerprint_datapoints" \
    --collect-all "language_tags" \
    --collect-all "keyring" \
    --hidden-import "keyring.backends.Windows" \
    --hidden-import "keyring.backends.macOS" \
    main.py

if [ ! -f "dist/blm-backend/blm-backend" ]; then
    echo "ERROR: PyInstaller reported success but dist/blm-backend/blm-backend is missing. Refusing to package without a backend." >&2
    exit 1
fi

chmod +x "dist/blm-backend/blm-backend"

if [[ "$(uname -s)" == "Darwin" ]]; then
    echo "Ad-hoc signing backend binaries for macOS Gatekeeper compatibility..."
    codesign --force --deep --sign - "dist/blm-backend"
fi

echo "Build complete! Executable is at backend/dist/blm-backend/blm-backend"
