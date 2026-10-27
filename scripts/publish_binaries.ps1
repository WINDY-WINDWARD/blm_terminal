param(
    [switch]$Build,
    [string]$Notes = ""
)

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

Write-Host ">>> Publishing BLM Terminal $Version to $GithubRepo..." -ForegroundColor Cyan

# 2. Optional rebuild. This is NOT the default: the OTA manifest has to be
# signed AFTER the installer exists, and a rebuild here would delete the
# manifest that was just signed (the v2026.10.9 flow had to upload it by hand
# for exactly that reason). Pass -Build only when you intentionally want a
# fresh, unsigned build.
if ($Build) {
    Write-Host ">>> Cleaning previous desktop build artifacts..." -ForegroundColor Yellow
    if (Test-Path $DistDesktopDir) {
        Get-ChildItem -Path $DistDesktopDir -File | Where-Object {
            $_.Extension -eq ".exe" -or $_.Extension -eq ".yml" -or $_.Extension -eq ".blockmap" -or $_.Name -like "ota-manifest.*"
        } | Remove-Item -Force
    }
    Write-Host ">>> Building desktop artifacts (full sequential build)..." -ForegroundColor Yellow
    Set-Location $ProjectRoot
    npm run build:desktop
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Desktop build failed."
        exit 1
    }
}

# 3. Every release carries exactly these five assets. Fail early and tell the
# operator what to do, rather than publishing an incomplete release that OTA
# clients cannot verify.
$Installer = Join-Path $DistDesktopDir "BLM Terminal Setup $Version.exe"
$BlockMap = "$Installer.blockmap"
$LatestYml = Join-Path $DistDesktopDir "latest.yml"
$OtaManifest = Join-Path $DistDesktopDir "ota-manifest.json"
$OtaSignature = Join-Path $DistDesktopDir "ota-manifest.sig"

$Required = @($Installer, $BlockMap, $LatestYml, $OtaManifest, $OtaSignature)
$Missing = $Required | Where-Object { -not (Test-Path $_) }
if ($Missing.Count -gt 0) {
    Write-Host ">>> Missing release artifacts for ${Version}:" -ForegroundColor Red
    $Missing | ForEach-Object { Write-Host "    $_" -ForegroundColor Red }
    Write-Host ""
    Write-Host ">>> Build and sign first, then re-run this script:" -ForegroundColor Yellow
    Write-Host "    1. npm run build:desktop" -ForegroundColor Yellow
    Write-Host "    2. node ..\blmlanding\scripts\sign-ota-manifest.js $Version `"$Installer`" ..\blmlanding\ota-key-offline-DO-NOT-COMMIT.json dist-desktop\ota-manifest" -ForegroundColor Yellow
    Write-Host "    3. npm run publish:binaries" -ForegroundColor Yellow
    exit 1
}

# 4. Hard gate. verify:release checks the signature, the manifest, the installer
# hashes and latest.yml; nothing is published if any check fails.
Write-Host ">>> Verifying release artifacts..." -ForegroundColor Yellow
Set-Location $ProjectRoot
npm run verify:release
if ($LASTEXITCODE -ne 0) {
    Write-Error "verify:release failed. Refusing to publish."
    exit 1
}

# 4b. The verifier must also work INSIDE the packaged app: asar packing and
# libsodium's wasm are exactly the things that break silently and turn every
# future update dark. Run the un-packaged binary in verification mode; a
# non-zero exit means "do not publish".
$UnpackedExe = Join-Path $DistDesktopDir "win-unpacked\BLM Terminal.exe"
if (Test-Path $UnpackedExe) {
    Write-Host ">>> Verifying the packaged OTA verifier (--verify-ota)..." -ForegroundColor Yellow
    $VerifyProc = Start-Process -FilePath $UnpackedExe -ArgumentList "--verify-ota" -Wait -PassThru
    if ($VerifyProc.ExitCode -ne 0) {
        Write-Error "Packaged app failed --verify-ota (exit $($VerifyProc.ExitCode)). The OTA verifier is broken in this build; do not publish."
        exit 1
    }
    Write-Host ">>> Packaged verifier OK." -ForegroundColor Cyan
} else {
    Write-Host ">>> WARNING: $UnpackedExe not found; skipped the packaged verifier check." -ForegroundColor Red
}

# 5. The remote tag must already exist and point at the current commit.
# Otherwise `gh release create` silently creates the tag on the remote's default
# branch, which is how a release once shipped code that was not its own.
$LocalTagCommit = (git rev-parse "$TagName" 2>$null)
if ($LASTEXITCODE -ne 0 -or -not $LocalTagCommit) {
    Write-Error "Tag $TagName does not exist locally. Run 'npm run release' first."
    exit 1
}
$RemoteTagLine = (git ls-remote --tags origin "refs/tags/$TagName" 2>$null)
if (-not $RemoteTagLine) {
    Write-Error "Tag $TagName is not pushed yet. Run: git push origin HEAD && git push origin refs/tags/$TagName"
    exit 1
}
if ($RemoteTagLine -notmatch [regex]::Escape($LocalTagCommit)) {
    Write-Error "Remote tag $TagName does not point at local commit $LocalTagCommit."
    exit 1
}
Write-Host ">>> Tag $TagName is pushed and matches the local commit." -ForegroundColor Cyan

$Artifacts = @($Installer, $BlockMap, $LatestYml, $OtaManifest, $OtaSignature)
Write-Host ">>> Publishing $($Artifacts.Count) artifacts." -ForegroundColor Cyan

# 6. Create or update the GitHub Release using gh
try {
    $null = gh --version
} catch {
    Write-Error "GitHub CLI (gh) is not installed or not in PATH. Please install it and run 'gh auth login' before publishing."
    exit 1
}

$ErrorActionPreference = "Continue"
$ReleaseCheck = gh release view $TagName --repo $GithubRepo 2>&1
$ReleaseExists = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = "Stop"

if ($ReleaseExists) {
    Write-Host "Release $TagName already exists. Uploading artifacts with --clobber..." -ForegroundColor Yellow
    gh release upload $TagName @Artifacts --repo $GithubRepo --clobber
} else {
    Write-Host "Creating new release $TagName..." -ForegroundColor Yellow
    $Title = "BLM Terminal $Version"
    if (-not $Notes) { $Notes = "Release version $Version" }
    gh release create $TagName @Artifacts --repo $GithubRepo --title $Title --notes $Notes
}

if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to publish release artifacts to GitHub Releases."
    exit 1
}

# 7. Confirm the release really carries five assets. v2026.10.9 shipped a sixth
# (builder-debug.yml) because the old filter took every .yml in the folder.
Write-Host ">>> Verifying published assets..." -ForegroundColor Yellow
$ErrorActionPreference = "Continue"
$AssetNames = gh release view $TagName --repo $GithubRepo --json assets --jq ".assets[].name" 2>&1
$ErrorActionPreference = "Stop"
# GitHub rewrites spaces in asset names to dots ("BLM Terminal Setup X.exe"
# becomes "BLM.Terminal.Setup.X.exe"), so compare on the normalised form. The
# landing portal maps the dotted name back when it serves latest.yml's path.
function ConvertTo-AssetKey([string]$Name) { return ($Name -replace '\s', '.') }

$ExpectedNames = @(
    "BLM Terminal Setup $Version.exe",
    "BLM Terminal Setup $Version.exe.blockmap",
    "latest.yml",
    "ota-manifest.json",
    "ota-manifest.sig"
) | ForEach-Object { ConvertTo-AssetKey $_ }
$PublishedNames = @($AssetNames | Where-Object { $_ -and $_ -notmatch '^\s*$' } | ForEach-Object { ConvertTo-AssetKey $_ })
foreach ($name in $ExpectedNames) {
    if ($PublishedNames -notcontains $name) {
        Write-Error "Published release is missing asset: $name"
        exit 1
    }
}
$Unexpected = $PublishedNames | Where-Object { $ExpectedNames -notcontains $_ }
if ($Unexpected.Count -gt 0) {
    Write-Host ">>> WARNING: unexpected extra assets on the release:" -ForegroundColor Red
    $Unexpected | ForEach-Object { Write-Host "    $_" -ForegroundColor Red }
}

Write-Host ">>> Successfully published $TagName with $($ExpectedNames.Count) verified assets." -ForegroundColor Green
Write-Host ">>> Final check once the portal cache expires (~5 min): npm run verify:release:live" -ForegroundColor Green
