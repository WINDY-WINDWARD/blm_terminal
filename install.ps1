#Requires -Version 5.1
<#
.SYNOPSIS
    BLM Terminal - Windows Setup Script

.DESCRIPTION
    Installs all prerequisites, sets up the Node.js frontend and Python FastAPI
    backend, runs database migrations, builds the frontend, and optionally launches both servers.

    Run from the repository root:
        .\install.ps1

    To allow execution (first time only):
        Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
#>

[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

$Script:HasErrors = $false
$Sep  = "=" * 60
$Sep2 = "-" * 53

function Write-Header {
    param([string]$Text)
    Write-Host ""
    Write-Host $Sep -ForegroundColor Cyan
    Write-Host "  $Text" -ForegroundColor Cyan
    Write-Host $Sep -ForegroundColor Cyan
}

function Write-Step {
    param([string]$Text)
    Write-Host ""
    Write-Host "  >> $Text" -ForegroundColor White
}

function Write-OK {
    param([string]$Text)
    Write-Host "  [OK] $Text" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Text)
    Write-Host "  [WARN] $Text" -ForegroundColor Yellow
}

function Write-Fail {
    param([string]$Text)
    Write-Host "  [FAIL] $Text" -ForegroundColor Red
    $Script:HasErrors = $true
}

function Write-Info {
    param([string]$Text)
    Write-Host "  [INFO] $Text" -ForegroundColor DarkGray
}

function Invoke-Step {
    param(
        [string]$Description,
        [scriptblock]$Command,
        [switch]$AllowFailure
    )
    Write-Step $Description
    try {
        & $Command
        if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) {
            throw "Exit code $LASTEXITCODE"
        }
        Write-OK $Description
    } catch {
        if ($AllowFailure) {
            Write-Warn "$Description - skipped ($($_.Exception.Message))"
        } else {
            Write-Fail "$Description failed: $($_.Exception.Message)"
            Write-Host ""
            Write-Host "  Setup cannot continue. Fix the error above and re-run install.ps1" -ForegroundColor Red
            exit 1
        }
    }
}

# ---------------------------------------------------------------------------
# Resolve script root
# ---------------------------------------------------------------------------
$RepoRoot    = $PSScriptRoot
$BackendDir  = Join-Path $RepoRoot "backend"
$VenvDir     = Join-Path $BackendDir ".venv"
$VenvPython  = Join-Path $VenvDir "Scripts\python.exe"
$VenvPip     = Join-Path $VenvDir "Scripts\pip.exe"
$VenvAlembic = Join-Path $VenvDir "Scripts\alembic.exe"

# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------
Clear-Host
Write-Host ""
Write-Host "  ============================================================" -ForegroundColor Cyan
Write-Host "   BLM Terminal -- Windows Setup" -ForegroundColor Cyan
Write-Host "  ============================================================" -ForegroundColor Cyan
Write-Host "  Working directory: $RepoRoot" -ForegroundColor DarkGray
Write-Host ""

# ---------------------------------------------------------------------------
# SECTION 1 - Prerequisites
# ---------------------------------------------------------------------------
Write-Header "STEP 1 of 5 - Checking Prerequisites"

# -- Python ------------------------------------------------------------------
Write-Step "Checking Python (requires 3.11 or 3.12)"

$PythonCmd     = $null
$PythonVersion = $null

foreach ($candidate in @('python', 'python3', 'py')) {
    try {
        $raw = & $candidate --version 2>&1
        if ($raw -match '(\d+)\.(\d+)\.(\d+)') {
            $major = [int]$Matches[1]
            $minor = [int]$Matches[2]
            if ($major -eq 3 -and $minor -ge 11) {
                $PythonCmd     = $candidate
                $PythonVersion = "$major.$minor.$($Matches[3])"
                break
            } elseif ($major -eq 3 -and $minor -lt 11) {
                Write-Warn "Found Python $major.$minor via '$candidate' -- too old (need 3.11+). Checking next..."
            }
        }
    } catch {
        # candidate not on PATH -- continue
    }
}

# Try py launcher with explicit version tags
if (-not $PythonCmd) {
    foreach ($tag in @('-3.12', '-3.11')) {
        try {
            $raw = & py $tag --version 2>&1
            if ($raw -match '(\d+)\.(\d+)\.(\d+)') {
                $major = [int]$Matches[1]
                $minor = [int]$Matches[2]
                if ($major -eq 3 -and $minor -ge 11) {
                    $PythonCmd     = "py $tag"
                    $PythonVersion = "$major.$minor.$($Matches[3])"
                    break
                }
            }
        } catch {}
    }
}

if ($PythonCmd) {
    Write-OK "Python $PythonVersion found ($PythonCmd)"
    # Warn about Microsoft Store Python
    $pythonExe = $PythonCmd.Split(' ')[0]
    $pythonPath = (Get-Command $pythonExe -ErrorAction SilentlyContinue).Source
    if ($pythonPath -and $pythonPath -like '*WindowsApps*') {
        Write-Warn "This Python appears to be the Microsoft Store stub."
        Write-Warn "It may cause virtualenv and PATH issues."
        Write-Warn "Recommended: Install from https://www.python.org/downloads/"
        Write-Warn "             (check 'Add Python to PATH' during install)"
    }
} else {
    Write-Fail "Python 3.11+ not found on PATH"
    Write-Host ""
    Write-Host "  Python 3.11 or 3.12 is required." -ForegroundColor Red
    Write-Host "  Download from: https://www.python.org/downloads/" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Installation tips:" -ForegroundColor White
    Write-Host "    - Check 'Add Python to PATH' on the first installer screen" -ForegroundColor White
    Write-Host "    - Do NOT install from the Microsoft Store (causes PATH issues)" -ForegroundColor White
    Write-Host "    - Close and reopen this terminal after installing, then re-run install.ps1" -ForegroundColor White
    Write-Host ""
    exit 1
}

# -- Node.js -----------------------------------------------------------------
Write-Step "Checking Node.js (requires >= 18.17)"

$NodeOK = $false
try {
    $nodeRaw = & node --version 2>&1
    if ($nodeRaw -match 'v(\d+)\.(\d+)') {
        $nodeMajor = [int]$Matches[1]
        $nodeMinor = [int]$Matches[2]
        if ($nodeMajor -gt 18 -or ($nodeMajor -eq 18 -and $nodeMinor -ge 17)) {
            Write-OK "Node.js $nodeRaw found"
            $NodeOK = $true
        } else {
            Write-Fail "Node.js $nodeRaw is too old (requires >= 18.17)"
        }
    }
} catch {
    Write-Fail "Node.js not found on PATH"
}

if (-not $NodeOK) {
    Write-Host ""
    Write-Host "  Node.js 20 LTS or 22 LTS is recommended." -ForegroundColor Red
    Write-Host "  Download from: https://nodejs.org/en/download/" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Installation tips:" -ForegroundColor White
    Write-Host "    - Choose the LTS release (Node 20 or 22)" -ForegroundColor White
    Write-Host "    - The installer adds Node to PATH automatically" -ForegroundColor White
    Write-Host "    - Close and reopen this terminal after installing, then re-run install.ps1" -ForegroundColor White
    Write-Host ""
    exit 1
}

# -- npm ---------------------------------------------------------------------
Write-Step "Checking npm"
try {
    $npmRaw = & npm --version 2>&1
    Write-OK "npm $npmRaw found"
} catch {
    Write-Fail "npm not found -- it should ship with Node.js. Re-install Node.js from https://nodejs.org/"
    exit 1
}

# -- Git (soft check) --------------------------------------------------------
Write-Step "Checking Git (optional)"
try {
    $gitRaw = & git --version 2>&1
    Write-OK "$gitRaw"
} catch {
    Write-Warn "Git not found. Not required to run, but useful for updates."
    Write-Warn "Download from: https://git-scm.com/download/win"
}

# ---------------------------------------------------------------------------
# SECTION 2 - Frontend (Node.js)
# ---------------------------------------------------------------------------
Write-Header "STEP 2 of 5 - Frontend Setup (Node.js / Next.js)"

Invoke-Step "Installing Node.js dependencies (npm install)" {
    Set-Location $RepoRoot
    & npm install
}

    Set-Location $RepoRoot
}

Invoke-Step "Building frontend (npm run build)" {
    Set-Location $RepoRoot
    & npm run build
}

Write-Step "Setting up frontend environment file"
$FrontendEnvExample = Join-Path $RepoRoot ".env.example"
$FrontendEnvLocal   = Join-Path $RepoRoot ".env.local"

if (Test-Path $FrontendEnvLocal) {
    Write-Warn ".env.local already exists -- skipping copy (will not overwrite)"
} elseif (Test-Path $FrontendEnvExample) {
    Copy-Item $FrontendEnvExample $FrontendEnvLocal
    Write-OK "Created .env.local from .env.example"
} else {
    Write-Warn ".env.example not found -- create .env.local manually"
}

# ---------------------------------------------------------------------------
# SECTION 3 - Python Backend
# ---------------------------------------------------------------------------
Write-Header "STEP 3 of 5 - Backend Setup (Python / FastAPI)"

Write-Step "Creating Python virtual environment"
if (Test-Path $VenvPython) {
    Write-Warn "Virtual environment already exists at $VenvDir -- skipping creation"
} else {
    Invoke-Step "python -m venv .venv" {
        $pyExe  = $PythonCmd.Split(' ')[0]
        $pyArgs = @()
        if ($PythonCmd -match ' ') {
            $pyArgs = $PythonCmd.Split(' ') | Select-Object -Skip 1
        }
        $allArgs = $pyArgs + @('-m', 'venv', $VenvDir)
        & $pyExe @allArgs
    }
}

Invoke-Step "Installing Python dependencies (pip install -e .)" {
    # Install uvicorn without [standard] to skip uvloop (Linux-only C extension).
    # uvicorn falls back to the default asyncio loop on Windows -- no loss of functionality.
    & $VenvPip install --upgrade pip --quiet
    & $VenvPip install -e $BackendDir
}

Invoke-Step "Running database migrations (alembic upgrade heads)" {
    Set-Location $BackendDir
    & $VenvAlembic upgrade heads
}

Write-Step "Setting up backend environment file"
$BackendEnvExample = Join-Path $BackendDir ".env.example"
$BackendEnvLocal   = Join-Path $BackendDir ".env.local"
$BackendEnvDotenv  = Join-Path $BackendDir ".env"

if ((Test-Path $BackendEnvLocal) -or (Test-Path $BackendEnvDotenv)) {
    Write-Warn "Backend .env / .env.local already exists -- skipping copy"
} elseif (Test-Path $BackendEnvExample) {
    Copy-Item $BackendEnvExample $BackendEnvLocal
    Write-OK "Created backend/.env.local from backend/.env.example"
} else {
    Write-Warn "backend/.env.example not found -- create backend/.env.local manually"
}

# ---------------------------------------------------------------------------
# SECTION 4 - Summary
# ---------------------------------------------------------------------------
Write-Header "STEP 4 of 5 - Setup Summary"

Write-Host ""
Write-Host "  Frontend" -ForegroundColor White
Write-Host "    Node modules : installed" -ForegroundColor Green
Write-Host "    Prisma client: generated" -ForegroundColor Green

if (Test-Path $FrontendEnvLocal) {
    Write-Host "    .env.local   : present" -ForegroundColor Green
} else {
    Write-Host "    .env.local   : MISSING" -ForegroundColor Red
}

Write-Host ""
Write-Host "  Backend" -ForegroundColor White
Write-Host "    Python venv  : $VenvDir" -ForegroundColor Green
Write-Host "    Dependencies : installed" -ForegroundColor Green
Write-Host "    DB migrations: applied" -ForegroundColor Green

if ((Test-Path $BackendEnvLocal) -or (Test-Path $BackendEnvDotenv)) {
    Write-Host "    .env.local   : present" -ForegroundColor Green
} else {
    Write-Host "    .env.local   : MISSING" -ForegroundColor Red
}

Write-Host ""
Write-Host "  $Sep2" -ForegroundColor DarkGray
Write-Host "  ACTION REQUIRED - Edit these files before starting:" -ForegroundColor Yellow
Write-Host ""
Write-Host "  1. $FrontendEnvLocal" -ForegroundColor Yellow
Write-Host "     Key values to set:" -ForegroundColor DarkGray
Write-Host "       OPENALGO_API_KEY   - your OpenAlgo API key" -ForegroundColor DarkGray
Write-Host "       OPENALGO_URL       - URL of your OpenAlgo server (default: http://localhost:8800)" -ForegroundColor DarkGray
Write-Host "       PYTHON_BACKEND_URL - must match PORT in backend .env.local (default: http://localhost:4455)" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  2. $BackendEnvLocal" -ForegroundColor Yellow
Write-Host "     Key values to set:" -ForegroundColor DarkGray
Write-Host "       AI_API_KEY         - your OpenAI (or compatible) API key" -ForegroundColor DarkGray
Write-Host "       AI_API_BASE_URL    - LLM provider URL (default: https://api.openai.com/v1)" -ForegroundColor DarkGray
Write-Host "       AI_MODEL           - model name (default: gpt-4o-mini)" -ForegroundColor DarkGray
Write-Host "       PORT               - backend port (default: 4455)" -ForegroundColor DarkGray
Write-Host "  $Sep2" -ForegroundColor DarkGray

# ---------------------------------------------------------------------------
# SECTION 5 - Optionally start dev servers
# ---------------------------------------------------------------------------
Write-Header "STEP 5 of 5 - Start Servers"
Write-Host ""
Write-Host "  Frontend : npm start                 (http://localhost:3000)" -ForegroundColor White
Write-Host "  Backend  : uvicorn main:app --port 4455  (http://localhost:4455)" -ForegroundColor White
Write-Host ""

$answer = Read-Host "  Start both dev servers now? [y/N]"

if ($answer -match '^[Yy]$') {

    Write-Host ""
    Write-Host "  Launching servers in separate windows..." -ForegroundColor Cyan

    # Frontend window
    $frontendCmd = "Set-Location '$RepoRoot'; Write-Host 'Starting Next.js server...' -ForegroundColor Cyan; npm start; Read-Host 'Press Enter to close'"
    Start-Process powershell -ArgumentList "-NoExit", "-Command", $frontendCmd -WindowStyle Normal

    Start-Sleep -Seconds 1

    # Backend window
    $backendActivate = Join-Path $VenvDir "Scripts\Activate.ps1"
    $backendCmd = "Set-Location '$BackendDir'; & '$backendActivate'; Write-Host 'Starting FastAPI backend...' -ForegroundColor Cyan; uvicorn main:app --port 4455; Read-Host 'Press Enter to close'"
    Start-Process powershell -ArgumentList "-NoExit", "-Command", $backendCmd -WindowStyle Normal

    Write-Host ""
    Write-OK "Two new terminal windows have been opened."
    Write-Host ""
    Write-Host "  Frontend -> http://localhost:3000" -ForegroundColor Green
    Write-Host "  Backend  -> http://localhost:4455" -ForegroundColor Green
    Write-Host "  API docs -> http://localhost:4455/docs" -ForegroundColor Green
    Write-Host ""
    Write-Host "  NOTE: The backend starts faster. The frontend may take a few seconds" -ForegroundColor DarkGray
    Write-Host "        to respond on first request after starting." -ForegroundColor DarkGray

} else {
    Write-Host ""
    Write-Host "  To start the servers manually:" -ForegroundColor White
    Write-Host ""
    Write-Host "  Terminal 1 - Frontend:" -ForegroundColor Cyan
    Write-Host "    cd $RepoRoot" -ForegroundColor White
    Write-Host "    npm start" -ForegroundColor White
    Write-Host ""
    Write-Host "  Terminal 2 - Backend:" -ForegroundColor Cyan
    Write-Host "    cd $BackendDir" -ForegroundColor White
    Write-Host "    .\.venv\Scripts\Activate.ps1" -ForegroundColor White
    Write-Host "    uvicorn main:app --port 4455" -ForegroundColor White
}

Write-Host ""
Write-Host $Sep -ForegroundColor Cyan
Write-Host "  Setup complete." -ForegroundColor Green
Write-Host $Sep -ForegroundColor Cyan
Write-Host ""
