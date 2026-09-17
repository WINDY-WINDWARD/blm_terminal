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

# Install PyInstaller if missing
& $PythonCmd -m pip install pyinstaller

# Build the executable
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