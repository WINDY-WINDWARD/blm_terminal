$ErrorActionPreference = "Stop"

# Clear local proxy variables that interfere with network requests and CLI tools
Remove-Item env:HTTP_PROXY -ErrorAction SilentlyContinue
Remove-Item env:HTTPS_PROXY -ErrorAction SilentlyContinue
Remove-Item env:ALL_PROXY -ErrorAction SilentlyContinue
Remove-Item env:GIT_HTTP_PROXY -ErrorAction SilentlyContinue
Remove-Item env:GIT_HTTPS_PROXY -ErrorAction SilentlyContinue

# Define the repository structure
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$DistDesktopDir = Join-Path $ProjectRoot "dist-desktop"
$GithubRepo = "WINDY-WINDWARD/blm_terminal"

# 1. Read package.json to get the version
$PackageJsonPath = Join-Path $ProjectRoot "package.json"
$PackageJson = Get-Content $PackageJsonPath | ConvertFrom-Json
$Version = $PackageJson.version
$TagName = "v$Version"

Write-Host ">>> Starting binary publish process for version $Version..." -ForegroundColor Cyan

# 2. Clean stale desktop build artifacts
Write-Host ">>> Cleaning previous desktop build artifacts..." -ForegroundColor Yellow
if (Test-Path $DistDesktopDir) {
    Get-ChildItem -Path $DistDesktopDir -File | Where-Object {
        $_.Extension -eq ".exe" -or $_.Extension -eq ".yml" -or $_.Extension -eq ".blockmap" -or $_.Name -like "ota-manifest.*"
    } | Remove-Item -Force
}

# 3. Run the desktop build process
Write-Host ">>> Building desktop artifacts..." -ForegroundColor Yellow
Set-Location $ProjectRoot
npm run build:desktop

# 4. Check for the output directory
if (-not (Test-Path $DistDesktopDir)) {
    Write-Error "Build output directory not found: $DistDesktopDir"
    exit 1
}

# 5. Find artifacts to upload (.exe, latest.yml, .blockmap)
#
# Only electron-builder's own latest.yml is release metadata. A blanket
# ".yml" filter also swept up builder-debug.yml, which shipped v2026.10.9 with
# a sixth, meaningless asset (every earlier release had exactly five).
$Artifacts = Get-ChildItem -Path $DistDesktopDir -File | Where-Object {
    ($_.Extension -eq ".exe" -and $_.Name -like "*$Version*") -or
    $_.Name -eq "latest.yml" -or
    ($_.Extension -eq ".blockmap" -and $_.Name -like "*$Version*")
}

if ($Artifacts.Count -eq 0) {
    Write-Error "No build artifacts found in $DistDesktopDir"
    exit 1
}

Write-Host ">>> Found $($Artifacts.Count) artifacts for release." -ForegroundColor Cyan

# 6. Create the GitHub Release using gh cli
Write-Host ">>> Publishing GitHub Release $TagName on $GithubRepo (blm_terminal)..." -ForegroundColor Yellow

try {
    # Check if gh is available
    $null = gh --version
} catch {
    Write-Error "GitHub CLI (gh) is not installed or not in PATH. Please install it and run 'gh auth login' before publishing."
    exit 1
}

# Check if release exists, if so, we upload/overwrite. Otherwise, create.
$ErrorActionPreference = "Continue"
$ReleaseCheck = gh release view $TagName --repo $GithubRepo 2>&1
$ErrorActionPreference = "Stop"

$ArtifactPaths = $Artifacts | ForEach-Object { $_.FullName }
if ($LASTEXITCODE -eq 0) {
    Write-Host "Release $TagName already exists. Uploading artifacts with --clobber..." -ForegroundColor Yellow
    gh release upload $TagName @ArtifactPaths --repo $GithubRepo --clobber
} else {
    Write-Host "Creating new release $TagName..." -ForegroundColor Yellow
    $Title = "BLM Terminal $Version"
    $Notes = "Release version $Version"
    gh release create $TagName @ArtifactPaths --repo $GithubRepo --title $Title --notes $Notes
}

if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to publish release artifacts to GitHub Releases."
    exit 1
}

Write-Host ">>> Successfully published artifacts to GitHub Releases!" -ForegroundColor Green

# 7. The OTA manifest is NOT uploaded by this script: it must be signed after
# the build produced above (signing a pre-build manifest signs the wrong
# installer). Remind the operator instead of silently shipping five assets.
$OtaManifest = Join-Path $DistDesktopDir "ota-manifest.json"
$OtaSignature = Join-Path $DistDesktopDir "ota-manifest.sig"
if ((Test-Path $OtaManifest) -and (Test-Path $OtaSignature)) {
    Write-Host ">>> Reminder: upload the signed OTA manifest for ${Version}:" -ForegroundColor Yellow
    Write-Host "    gh release upload $TagName `"$OtaManifest`" `"$OtaSignature`" --repo $GithubRepo --clobber" -ForegroundColor Yellow
} else {
    Write-Host ">>> WARNING: ota-manifest.json / ota-manifest.sig are missing from $DistDesktopDir." -ForegroundColor Red
    Write-Host "    Sign the manifest for $Version and upload it, otherwise OTA clients cannot verify this release." -ForegroundColor Red
}
