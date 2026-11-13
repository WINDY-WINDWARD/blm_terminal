# Pinned CLIProxyAPI downloader and staging script for Windows.
# Stages official CLIProxyAPI from resources/cliproxyapi/PROVENANCE.json to vendor/cliproxyapi/runtime/cliproxyapi.exe.
param(
    [string]$TargetDir,
    [switch]$VerifyOnly,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

Import-Module Microsoft.PowerShell.Utility -ErrorAction SilentlyContinue
Add-Type -AssemblyName System.IO.Compression.FileSystem -ErrorAction SilentlyContinue

$RepoRoot = Split-Path -Parent $PSScriptRoot

$ProvenancePath = Join-Path $RepoRoot "resources\cliproxyapi\PROVENANCE.json"
if (-not (Test-Path -LiteralPath $ProvenancePath)) {
    Write-Error "PROVENANCE.json is missing at: $ProvenancePath"
    exit 1
}

try {
    $ProvenanceRaw = Get-Content -Raw -LiteralPath $ProvenancePath -Encoding UTF8
    $Provenance = $ProvenanceRaw | ConvertFrom-Json
} catch {
    Write-Error "Failed to parse PROVENANCE.json: $_"
    exit 1
}

if (-not $Provenance.version) {
    Write-Error "PROVENANCE.json is missing the required 'version' field."
    exit 1
}

$WinArch = $Provenance.architectures.windows_amd64
if (-not $WinArch) {
    Write-Error "PROVENANCE.json is missing the required 'architectures.windows_amd64' entry."
    exit 1
}

$Version = [string]$Provenance.version
$AssetName = [string]$WinArch.asset_name
$DownloadUrl = [string]$WinArch.download_url
$ExpectedSha256 = [string]$WinArch.sha256
$ExpectedBinarySha256 = [string]$WinArch.binary_sha256
$ArchiveBinaryName = [string]$WinArch.archive_binary_name
$TargetBinaryName = [string]$WinArch.target_binary_name

if (-not $TargetBinaryName) {
    $TargetBinaryName = "cliproxyapi.exe"
}
if (-not $ArchiveBinaryName) {
    $ArchiveBinaryName = "cli-proxy-api.exe"
}

if (-not $TargetDir) {
    $TargetDir = Join-Path $RepoRoot "vendor\cliproxyapi\runtime"
}
$TargetExe = Join-Path $TargetDir $TargetBinaryName

# Architecture check: reject Windows ARM64 explicitly
$Arch = $env:PROCESSOR_ARCHITECTURE
if ($Arch -match "ARM64") {
    Write-Error "Windows ARM64 is explicitly not supported for CLIProxyAPI sidecar."
    exit 1
}

function Get-Sha256Hash([string]$Path) {
    if (Get-Command Get-FileHash -ErrorAction SilentlyContinue) {
        return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
    }
    $stream = [System.IO.File]::OpenRead($Path)
    try {
        $sha = [System.Security.Cryptography.SHA256]::Create()
        $hashBytes = $sha.ComputeHash($stream)
        return (-join ($hashBytes | ForEach-Object { "{0:x2}" -f $_ })).ToLowerInvariant()
    } finally {
        $stream.Close()
    }
}

function Test-StagedBinary {
    if (-not (Test-Path -LiteralPath $TargetExe)) {
        return $false
    }
    $item = Get-Item -LiteralPath $TargetExe
    if ($item.Length -lt 1000000) {
        return $false
    }
    $actualBinHash = Get-Sha256Hash $TargetExe
    if ($actualBinHash -ne $ExpectedBinarySha256.ToLowerInvariant()) {
        return $false
    }
    return $true
}

if ($VerifyOnly) {
    if (Test-StagedBinary) {
        Write-Host "CLIProxyAPI $Version binary verified at: $TargetExe"
        exit 0
    } else {
        if (-not (Test-Path -LiteralPath $TargetExe)) {
            Write-Error "CLIProxyAPI $Version binary is missing at: $TargetExe. Run scripts/stage_cliproxyapi.ps1 to stage it from PROVENANCE.json."
        } else {
            $currentHash = Get-Sha256Hash $TargetExe
            Write-Error "CLIProxyAPI $Version binary failed checksum verification at: $TargetExe. Expected: $ExpectedBinarySha256, Actual: $currentHash. Run scripts/stage_cliproxyapi.ps1 -Force to re-stage."
        }
        exit 1
    }
}

if ((Test-StagedBinary) -and (-not $Force)) {
    Write-Host "CLIProxyAPI $Version binary already staged and verified at: $TargetExe (use -Force to re-stage)"
    exit 0
}

Write-Host "Staging CLIProxyAPI $Version for Windows x64..."
New-Item -ItemType Directory -Force -Path $TargetDir | Out-Null

$TempZip = Join-Path $TargetDir "download-$AssetName.tmp.zip"
try {
    Write-Host "Downloading $DownloadUrl..."
    $curlCmd = Get-Command curl.exe -ErrorAction SilentlyContinue
    if ($curlCmd) {
        & curl.exe -sSL --fail -o $TempZip $DownloadUrl
        if ($LASTEXITCODE -ne 0) {
            throw "curl.exe failed to download asset from $DownloadUrl"
        }
    } else {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 -bor [Net.SecurityProtocolType]::Tls13
        Invoke-WebRequest -Uri $DownloadUrl -OutFile $TempZip -UseBasicParsing
    }

    Write-Host "Verifying archive SHA-256 checksum..."
    $ActualArchiveHash = Get-Sha256Hash $TempZip
    if ($ActualArchiveHash -ne $ExpectedSha256.ToLowerInvariant()) {
        throw "Archive checksum mismatch for $AssetName! Expected $ExpectedSha256, got $ActualArchiveHash"
    }
    Write-Host "Archive checksum verified: $ActualArchiveHash"

    Write-Host "Extracting $ArchiveBinaryName..."
    $ExtractSubdir = Join-Path $TargetDir "extract-tmp"
    if (Test-Path -LiteralPath $ExtractSubdir) {
        Remove-Item -LiteralPath $ExtractSubdir -Recurse -Force
    }
    Expand-Archive -LiteralPath $TempZip -DestinationPath $ExtractSubdir -Force
    try {
        $ExtractedExe = Join-Path $ExtractSubdir $ArchiveBinaryName
        if (-not (Test-Path -LiteralPath $ExtractedExe)) {
            throw "Archive does not contain $ArchiveBinaryName!"
        }
        $ActualBinHash = Get-Sha256Hash $ExtractedExe
        if ($ActualBinHash -ne $ExpectedBinarySha256.ToLowerInvariant()) {
            throw "Extracted binary checksum mismatch! Expected $ExpectedBinarySha256, got $ActualBinHash"
        }
        if (Test-Path -LiteralPath $TargetExe) {
            Remove-Item -LiteralPath $TargetExe -Force
        }
        Move-Item -LiteralPath $ExtractedExe -Destination $TargetExe -Force
    } finally {
        if (Test-Path -LiteralPath $ExtractSubdir) {
            Remove-Item -LiteralPath $ExtractSubdir -Recurse -Force -ErrorAction SilentlyContinue
        }
    }

    Write-Host "Successfully staged CLIProxyAPI $Version at: $TargetExe"
} finally {
    if (Test-Path -LiteralPath $TempZip) {
        Remove-Item -LiteralPath $TempZip -Force -ErrorAction SilentlyContinue
    }
}
