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
& $PyInstallerCmd `
    --name blm-backend `
    --onefile `
    --add-data "alembic;alembic" `
    --add-data "alembic.ini;." `
    --add-data "app/assets;app/assets" `
    --hidden-import "aiosqlite" `
    --hidden-import "sqlalchemy.dialects.sqlite" `
    --hidden-import "rookiepy" `
    --hidden-import "newspaper" `
    --hidden-import "newspaper.extractors" `
    --hidden-import "passlib.handlers.bcrypt" `
    main.py

Write-Host "Build complete! Executable is at backend\dist\blm-backend.exe"