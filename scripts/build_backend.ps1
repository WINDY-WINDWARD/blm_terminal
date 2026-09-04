$ErrorActionPreference = "Stop"

Write-Host "Building BLM Backend using PyInstaller..."

# Move into backend directory
Set-Location -Path "$PSScriptRoot\..\backend"

# Ensure venv exists and is activated (assumes it's installed there)
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Virtual environment not found. Please install requirements first."
    exit 1
}

# Install PyInstaller if missing
& .venv\Scripts\python.exe -m pip install pyinstaller

# Build the executable
& .venv\Scripts\pyinstaller.exe `
    --name blm-backend `
    --onefile `
    --add-data "alembic;alembic" `
    --add-data "alembic.ini;." `
    --hidden-import "aiosqlite" `
    --hidden-import "sqlalchemy.dialects.sqlite" `
    --hidden-import "rookiepy" `
    --hidden-import "newspaper" `
    --hidden-import "newspaper.extractors" `
    --hidden-import "passlib.handlers.bcrypt" `
    main.py

Write-Host "Build complete! Executable is at backend\dist\blm-backend.exe"