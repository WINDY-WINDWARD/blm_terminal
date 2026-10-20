# Pinned CLIProxyAPI downloader and staging script for Windows.
# Stages official CLIProxyAPI v8.0.35 to vendor/cliproxyapi/runtime/cliproxyapi.exe.
param(
    [string]$TargetDir,
    [switch]$VerifyOnly,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.IO.Compression.FileSystem -ErrorAction SilentlyContinue

$RepoRoot = Split-Path -Parent $PSScriptRoot
if (-not $TargetDir) {
    $TargetDir = Join-Path $RepoRoot "vendor\cliproxyapi\runtime"
}

$Version = "v8.0.35"
$AssetName = "CLIProxyAPI_8.0.35_windows_amd64.zip"
$ExpectedSha256 = "175a79c47705408c4ee95ff78cafb50a0542a010d3fac333162f10f0b9dbea88"
$DownloadUrl = "https://github.com/router-for-me/CLIProxyAPI/releases/download/$Version/$AssetName"
$TargetExe = Join-Path $TargetDir "cliproxyapi.exe"

# Architecture check: reject Windows ARM64 explicitly
$Arch = $env:PROCESSOR_ARCHITECTURE
if ($Arch -match "ARM64") {
    Write-Error "Windows ARM64 is explicitly not supported for CLIProxyAPI sidecar."
    exit 1
}

function Test-StagedBinary {
    if (-not (Test-Path -LiteralPath $TargetExe)) {
        return $false
    }
    $item = Get-Item -LiteralPath $TargetExe
    if ($item.Length -lt 1000000) {
        return $false
    }
    return $true
}

if ($VerifyOnly) {
    if (Test-StagedBinary) {
        Write-Host "CLIProxyAPI binary verified at: $TargetExe"
        exit 0
    } else {
        Write-Error "CLIProxyAPI binary is missing or invalid at: $TargetExe. Run scripts/stage_cliproxyapi.ps1 to stage it."
        exit 1
    }
}

if ((Test-StagedBinary) -and (-not $Force)) {
    Write-Host "CLIProxyAPI binary already staged at: $TargetExe (use -Force to re-stage)"
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

    Write-Host "Verifying SHA-256 checksum..."
    $ActualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $TempZip).Hash.ToLowerInvariant()
    if ($ActualHash -ne $ExpectedSha256.ToLowerInvariant()) {
        throw "Checksum mismatch for $AssetName! Expected $ExpectedSha256, got $ActualHash"
    }
    Write-Host "Checksum verified: $ActualHash"

    Write-Host "Extracting cli-proxy-api.exe..."
    $ExtractSubdir = Join-Path $TargetDir "extract-tmp"
    if (Test-Path -LiteralPath $ExtractSubdir) {
        Remove-Item -LiteralPath $ExtractSubdir -Recurse -Force
    }
    Expand-Archive -LiteralPath $TempZip -DestinationPath $ExtractSubdir -Force
    try {
        $ExtractedExe = Join-Path $ExtractSubdir "cli-proxy-api.exe"
        if (-not (Test-Path -LiteralPath $ExtractedExe)) {
            throw "Archive does not contain cli-proxy-api.exe!"
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

    Write-Host "Successfully staged CLIProxyAPI at: $TargetExe"
} finally {
    if (Test-Path -LiteralPath $TempZip) {
        Remove-Item -LiteralPath $TempZip -Force -ErrorAction SilentlyContinue
    }
}
