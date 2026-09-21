$ErrorActionPreference = "Stop"

Write-Host "Building BLM Backend using PyInstaller..."

# Move into backend directory
Set-Location -Path "$PSScriptRoot\..\backend"

# Determine python and pyinstaller executable paths
$PythonCmd = "python"
$PyInstallerCmd = "pyinstaller"

if (Test-Path ".venv\Scripts\python.exe") {
    Write-Host "Local virtual environment found. Using .venv"
    $PythonCmd = ".venv\Scripts\python.exe"
    $PyInstallerCmd = ".venv\Scripts\pyinstaller.exe"
} else {
    Write-Host "No local .venv found. Assuming global environment (e.g., GitHub Actions runner)."
}

# Install PyInstaller if missing (gated: skips the network round-trip when the
# local venv already has a working pyinstaller — the common case).
$PyInstallerOk = $false
try {
    & $PythonCmd -c "import PyInstaller; print(PyInstaller.__version__)" 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { $PyInstallerOk = $true }
} catch { $PyInstallerOk = $false }
if (-not $PyInstallerOk) {
    & $PythonCmd -m pip install pyinstaller
}

# Build the executable
# NOTE (2026-09-22): always wipe the PyInstaller work dirs first so every
# backend exe is built from current source. A reused backend/build/ cache is
# a silent stale-backend risk; the few minutes of a clean Analysis are
# non-negotiable for release integrity. (Separate real incident the same
# day: an orphaned blm-backend.exe survived reinstall and kept writing with
# old code — see the install discipline note in RELEASES.md.)
Remove-Item -Recurse -Force "build" -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force "dist" -ErrorAction SilentlyContinue
# --collect-all camoufox / apify_fingerprint_datapoints: Camoufox needs its
# bundled data files (e.g. input-network-definition.zip) at runtime. Without
# them the frozen exe fails to launch the persistent warm browser with
# "No such file or directory ... _MEI*/apify_fingerprint_datapoints/...".
# --exclude-module camoufox.gui: the optional Qt launcher UI for Camoufox,
# never imported by the backend (only camoufox + camoufox.sync_api are used).
# Without the exclusion, --collect-all trips over it and warns about the
# missing PySide6 dependency on every build.
& $PyInstallerCmd `
    --name blm-backend `
    --onefile `
    --add-data "alembic;alembic" `
    --add-data "alembic.ini;." `
    --add-data "app/assets;app/assets" `
    --hidden-import "aiosqlite" `
    --hidden-import "sqlalchemy.dialects.sqlite" `
    --hidden-import "newspaper" `
    --hidden-import "newspaper.extractors" `
    --hidden-import "passlib.handlers.bcrypt" `
    --collect-all "camoufox" `
    --exclude-module "camoufox.gui" `
    --collect-all "apify_fingerprint_datapoints" `
    --collect-all "language_tags" `
    main.py

Write-Host "Build complete! Executable is at backend\dist\blm-backend.exe"