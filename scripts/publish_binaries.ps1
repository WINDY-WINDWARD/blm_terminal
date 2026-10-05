$ErrorActionPreference = "Stop"

# Define the repository structure
$ProjectRoot = Resolve-Path ".."
$DistDesktopDir = Join-Path $ProjectRoot "dist-desktop"
$GithubRepo = "WINDY-WINDWARD/blmterminal-binaries"

# 1. Read package.json to get the version
$PackageJsonPath = Join-Path $ProjectRoot "package.json"
$PackageJson = Get-Content $PackageJsonPath | ConvertFrom-Json
$Version = $PackageJson.version
$TagName = "v$Version"

Write-Host ">>> Starting binary publish process for version $Version..." -ForegroundColor Cyan

# 2. Run the desktop build process
Write-Host ">>> Building desktop artifacts..." -ForegroundColor Yellow
Set-Location $ProjectRoot
npm run build:desktop

# 3. Check for the output directory
if (-not (Test-Path $DistDesktopDir)) {
    Write-Error "Build output directory not found: $DistDesktopDir"
    exit 1
}

# 4. Find artifacts to upload (.exe, latest.yml, .blockmap)
$Artifacts = Get-ChildItem -Path $DistDesktopDir -File | Where-Object { 
    $_.Extension -eq ".exe" -or $_.Extension -eq ".yml" -or $_.Extension -eq ".blockmap" 
}

if ($Artifacts.Count -eq 0) {
    Write-Error "No build artifacts found in $DistDesktopDir"
    exit 1
}

Write-Host ">>> Found $($Artifacts.Count) artifacts for release." -ForegroundColor Cyan

# 5. Create the GitHub Release using gh cli
Write-Host ">>> Creating GitHub Release $TagName on $GithubRepo..." -ForegroundColor Yellow

$ArtifactPaths = $Artifacts | ForEach-Object { $_.FullName }
$ArtifactPathsStr = $ArtifactPaths -join " "

try {
    # Check if gh is available
    $null = gh --version
} catch {
    Write-Error "GitHub CLI (gh) is not installed or not in PATH. Please install it and run 'gh auth login' before publishing."
    exit 1
}

# Check if release exists, if so, we upload/overwrite. Otherwise, create.
$ReleaseCheck = gh release view $TagName --repo $GithubRepo 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "Release $TagName already exists. Uploading artifacts..." -ForegroundColor Yellow
    Invoke-Expression "gh release upload $TagName $ArtifactPathsStr --repo $GithubRepo --clobber"
} else {
    Write-Host "Creating new release $TagName..." -ForegroundColor Yellow
    $Title = "BLM Terminal $Version"
    $Notes = "Release version $Version"
    Invoke-Expression "gh release create $TagName $ArtifactPathsStr --repo $GithubRepo --title `"$Title`" --notes `"$Notes`""
}

Write-Host ">>> Successfully published artifacts to GitHub Releases!" -ForegroundColor Green
