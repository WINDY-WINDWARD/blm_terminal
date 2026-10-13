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
$GithubRepo = "WINDY-WINDWARD/blmterminal-binaries"

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

Write-Host ">>> Generating signed OTA manifest..." -ForegroundColor Yellow
$LandingRoot = Join-Path (Split-Path -Parent $ProjectRoot) "blmlanding"
$SignScript = Join-Path $LandingRoot "scripts\sign-ota-manifest.js"
$OfflineKey = Join-Path $LandingRoot "ota-key-offline-DO-NOT-COMMIT.json"
$ExeFile = Get-ChildItem -Path $DistDesktopDir -Filter "*$Version*.exe" | Where-Object { $_.Name -like "*Setup*" } | Select-Object -First 1

if (-not $ExeFile) {
    Write-Error "Installer matching version $Version not found in $DistDesktopDir"
    exit 1
}

if (-not ($ExeFile.Name -like "*$Version*")) {
    Write-Error "Resolved installer '$($ExeFile.Name)' does not match target version $Version"
    exit 1
}
$OutBasename = Join-Path $DistDesktopDir "ota-manifest"

if (Test-Path $OfflineKey) {
    node $SignScript $Version $ExeFile.FullName $OfflineKey $OutBasename
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to sign OTA manifest"
        exit 1
    }
} else {
    Write-Error "Offline key not found at $OfflineKey. Refusing to publish unsigned OTA update!"
    exit 1
}

# 4. Run automated pre-flight integrity verification before uploading
Write-Host ">>> Running release pre-flight cryptographic and hash verification..." -ForegroundColor Yellow
$VerifyScript = Join-Path $ScriptDir "verify_release.js"
if (Test-Path $VerifyScript) {
    node $VerifyScript
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Release pre-flight verification FAILED! Refusing to publish invalid artifacts."
        exit 1
    }
} else {
    Write-Warning "verify_release.js not found at $VerifyScript; skipping automated pre-flight verification."
}

# 5. Check for the output directory
if (-not (Test-Path $DistDesktopDir)) {
    Write-Error "Build output directory not found: $DistDesktopDir"
    exit 1
}

# 6. Find artifacts to upload (.exe, latest.yml, .blockmap, .json, .sig)
$Artifacts = Get-ChildItem -Path $DistDesktopDir -File | Where-Object { 
    ($_.Extension -eq ".exe" -and $_.Name -like "*$Version*") -or 
    $_.Extension -eq ".yml" -or 
    ($_.Extension -eq ".blockmap" -and $_.Name -like "*$Version*") -or 
    $_.Name -eq "ota-manifest.json" -or 
    $_.Name -eq "ota-manifest.sig"
}

if ($Artifacts.Count -eq 0) {
    Write-Error "No build artifacts found in $DistDesktopDir"
    exit 1
}

Write-Host ">>> Found $($Artifacts.Count) artifacts for release." -ForegroundColor Cyan

# 7. Create the GitHub Release using gh cli
Write-Host ">>> Publishing GitHub Release $TagName on $GithubRepo..." -ForegroundColor Yellow

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
