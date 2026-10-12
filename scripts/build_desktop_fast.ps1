# Fast local desktop build.
#
# Runs the Next.js and backend builds CONCURRENTLY (they share no inputs) and
# skips any side whose inputs are unchanged since the last build (hash state
# in dist-desktop/.build-hashes.json). Packaging uses the standard
# electron-builder.json unchanged.
#
# RELEASE DISCIPLINE (enforced by docs, not by this script): version bumps,
# `gh release` flows, and `publish:desktop` MUST use the full sequential
# `npm run build:desktop`. This script is for local iteration only.
param([switch]$Full)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$HashFile = Join-Path $RepoRoot "dist-desktop/.build-hashes.json"

# Input sets. PowerShell 5.1 does NOT understand '**' globs — the previous
# 'backend/**/*.py' pattern silently matched (almost) nothing, which froze the
# hash and shipped stale builds (2026-09-28 EULA incident). Enumerate real
# directories with -Filter/-Recurse instead. Each set: Root (+ optional Filter,
# TopOnly for files directly in Root). Excluded path segments keep venvs and
# build outputs out of the hash.
$ExcludeDirs = @('.venv', 'dist', '__pycache__', 'node_modules', '.git', '.next')

$BackendInputs = @(
    @{ Root = 'backend'; Filter = '*.py' },
    @{ Root = 'backend'; Filter = 'alembic.ini'; TopOnly = $true },
    @{ Root = 'backend'; Filter = 'requirements*.txt'; TopOnly = $true }
)
$FrontendInputs = @(
    @{ Root = 'src' },
    @{ Root = 'electron' },
    @{ Root = 'server' },
    @{ Root = 'public' },
    @{ Root = '.'; Filter = 'server.js'; TopOnly = $true },
    @{ Root = '.'; Filter = 'package.json'; TopOnly = $true },
    @{ Root = '.'; Filter = 'package-lock.json'; TopOnly = $true },
    @{ Root = '.'; Filter = 'electron-builder.json'; TopOnly = $true },
    @{ Root = '.'; Filter = 'next.config.*'; TopOnly = $true },
    @{ Root = '.'; Filter = 'tsconfig*.json'; TopOnly = $true }
)

function Test-Excluded([System.IO.FileInfo]$f) {
    $rel = $f.FullName.Substring($RepoRoot.Length + 1)
    foreach ($seg in ($rel -split '[\\/]')) {
        if ($ExcludeDirs -contains $seg) { return $true }
    }
    return $false
}

function Get-InputHash([object[]]$Sets) {
    $files = foreach ($set in $Sets) {
        $root = Join-Path $RepoRoot $set.Root
        if (-not (Test-Path -LiteralPath $root)) { continue }
        $filter = $set.Filter
        if (-not $filter) { $filter = '*' }
        if ($set.TopOnly) {
            Get-ChildItem -LiteralPath $root -Filter $filter -File -ErrorAction SilentlyContinue
        } else {
            Get-ChildItem -LiteralPath $root -Filter $filter -File -Recurse -ErrorAction SilentlyContinue
        }
    }
    $files = $files | Where-Object { -not (Test-Excluded $_) } | Sort-Object FullName -Unique
    if (-not $files) { return "empty" }
    $sha = [System.Security.Cryptography.SHA256]::Create()
    foreach ($f in $files) {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($f.FullName)
        $sha.TransformBlock($bytes, 0, $bytes.Length, $null, 0) | Out-Null
        $stream = $f.OpenRead()
        try {
            $buf = New-Object byte[] 65536
            while (($n = $stream.Read($buf, 0, $buf.Length)) -gt 0) {
                $sha.TransformBlock($buf, 0, $n, $null, 0) | Out-Null
            }
        } finally { $stream.Close() }
    }
    $sha.TransformFinalBlock([byte[]]@(), 0, 0) | Out-Null
    return ([BitConverter]::ToString($sha.Hash)).Replace("-", "")
}

function Read-HashState {
    if (Test-Path $HashFile) {
        try { return Get-Content $HashFile -Raw | ConvertFrom-Json } catch { return $null }
    }
    return $null
}

$state = Read-HashState
$backendHash = Get-InputHash $BackendInputs
$frontendHash = Get-InputHash $FrontendInputs
$backendOut = Join-Path $RepoRoot "backend/dist/blm-backend.exe"
$frontendOut = Join-Path $RepoRoot ".next/BUILD_ID"

$skipBackend = (-not $Full) -and $state -and ($state.backendHash -eq $backendHash) -and (Test-Path $backendOut)
$skipFrontend = (-not $Full) -and $state -and ($state.frontendHash -eq $frontendHash) -and (Test-Path $frontendOut)

if ($skipBackend) { Write-Host "Backend inputs unchanged --- skipping PyInstaller (use -Full to force)." }
if ($skipFrontend) { Write-Host "Frontend inputs unchanged --- skipping Next.js build (use -Full to force)." }
if ($skipBackend -and $skipFrontend) { Write-Host "Nothing to rebuild --- packaging only." }

$jobs = @{}
if (-not $skipFrontend) {
    $jobs['frontend'] = Start-Job -Name "blm-next" -ScriptBlock {
        Set-Location $using:RepoRoot
        npm run build:next
        if ($LASTEXITCODE -ne 0) { throw "build:next failed with exit $LASTEXITCODE" }
    }
}
if (-not $skipBackend) {
    $jobs['backend'] = Start-Job -Name "blm-backend" -ScriptBlock {
        Set-Location $using:RepoRoot
        npm run build:backend
        if ($LASTEXITCODE -ne 0) { throw "build:backend failed with exit $LASTEXITCODE" }
    }
}

$failed = $false
foreach ($key in $jobs.Keys) {
    $job = $jobs[$key]
    Wait-Job $job | Out-Null
    # Receive-Job replays the child's stderr (npm/PyInstaller log to stderr)
    # as error records. Under $ErrorActionPreference "Stop" the first replayed
    # record would terminate THIS script, so drain with "Continue".
    $prevPref = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        Receive-Job $job
    } finally {
        $ErrorActionPreference = $prevPref
    }
    if ($job.State -ne 'Completed') {
        Write-Error "Build stage '$key' failed (state: $($job.State))."
        $failed = $true
    }
    Remove-Job $job -Force
}
if ($failed) { exit 1 }

# Package with the standard electron-builder.json (unchanged release settings).
# A "store compression" fast path was evaluated and rejected: NsisOptions in
# this electron-builder version has no compression knob (it exists only for
# linux/mac targets), so packaging speed cannot be tuned here. The fast wins
# are parallel stages + skipping unchanged sides.
Set-Location $RepoRoot
# Stale-frontend guard (2026-09-23 lesson): a hash-skip miss once shipped an
# installer whose .next CSS predated the sources (bulky native scrollbars in
# the running app). Prove the packaged CSS came from current sources before
# electron-builder runs — fail loudly instead of shipping stale UI.
$cssHit = Get-ChildItem -Path (Join-Path $RepoRoot ".next\static\*") -Recurse -Include *.css -ErrorAction SilentlyContinue |
    Select-String -Pattern "terminal-amber" -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $cssHit) {
    throw "Frontend CSS verification failed: no themed CSS (terminal-amber) under .next/static. The Next.js output is missing or stale -- run with -Full, then re-run."
}
# Same stderr-drain discipline as above: builder warnings must not terminate.
$prevPref = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
try {
    Remove-Item env:HTTP_PROXY -ErrorAction SilentlyContinue
    Remove-Item env:HTTPS_PROXY -ErrorAction SilentlyContinue
    Remove-Item env:ALL_PROXY -ErrorAction SilentlyContinue
    $env:ELECTRON_BUILDER_OFFLINE = 'true'
    npx electron-builder --win --config electron-builder.json -p never
    $builderExit = $LASTEXITCODE
} finally {
    $ErrorActionPreference = $prevPref
}
if ($builderExit -ne 0) { throw "electron-builder failed with exit $builderExit" }

# Record hashes for the sides that (re)built.
if (-not (Test-Path (Split-Path $HashFile))) {
    New-Item -ItemType Directory -Path (Split-Path $HashFile) -Force | Out-Null
}
@{ backendHash = $backendHash; frontendHash = $frontendHash } | ConvertTo-Json | Set-Content $HashFile
Write-Host "Fast build complete."
