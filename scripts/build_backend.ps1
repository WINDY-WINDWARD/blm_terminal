# BLM Terminal - PyInstaller Backend Build Script
$ErrorActionPreference = "Stop"

$ProjectRoot = (Get-Item -Path $PSScriptRoot\..).FullName
$BackendDir = Join-Path $ProjectRoot "backend"
$DistDir = Join-Path $ProjectRoot "dist-backend"

Write-Host "==> Project Root: $ProjectRoot"
Write-Host "==> Backend Dir:  $BackendDir"
Write-Host "==> Output Dir:   $DistDir"

# Determine path separator for --add-data (Windows uses ';', Linux/Mac uses ':')
$PathSep = if ($IsWindows -or $env:OS -like "*Windows*") { ";" } else { ":" }

$AlembicData = "$BackendDir/alembic${PathSep}alembic"
$AlembicIniData = "$BackendDir/alembic.ini${PathSep}."

Write-Host "==> Running PyInstaller..."

& pyinstaller `
    --name blm-backend `
    --onefile `
    --clean `
    --distpath $DistDir `
    --workpath "$DistDir/build" `
    --specpath "$DistDir" `
    --add-data $AlembicData `
    --add-data $AlembicIniData `
    --hidden-import aiosqlite `
    --hidden-import rookiepy `
    --hidden-import sqlalchemy.dialects.sqlite `
    --hidden-import uvicorn.logging `
    --hidden-import uvicorn.loops `
    --hidden-import uvicorn.loops.auto `
    --hidden-import uvicorn.protocols `
    --hidden-import uvicorn.protocols.http `
    --hidden-import uvicorn.protocols.http.auto `
    --hidden-import uvicorn.protocols.websockets `
    --hidden-import uvicorn.protocols.websockets.auto `
    --hidden-import uvicorn.lifespan `
    --hidden-import uvicorn.lifespan.on `
    --hidden-import alembic.context `
    --hidden-import app.models.system_config `
    "$BackendDir/main.py"

if ($LASTEXITCODE -ne 0) {
    Write-Error "PyInstaller build failed with exit code $LASTEXITCODE"
    exit $LASTEXITCODE
}

Write-Host "==> Backend build completed successfully: $DistDir/blm-backend.exe"
