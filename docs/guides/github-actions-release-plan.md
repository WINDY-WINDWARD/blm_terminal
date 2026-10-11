# Cross-Platform Release Architecture (GitHub Actions Plan)

This document outlines the architecture and setup required to allow any developer on any host OS (macOS, Windows, or Linux) to build and publish simultaneous Windows (`.exe`) and macOS (`.dmg`) releases of BLM Terminal.

---

## 1. Why Cloud Matrix Builds Are Required

BLM Terminal packages a standalone Python FastAPI backend via **PyInstaller** alongside the **Electron + Next.js** application:
- **PyInstaller does not support cross-compilation**: It freezes the active Python interpreter and native C extensions (`cryptography`, `lxml`, `scipy`, `numpy`, `camoufox`, `playwright`, `curl_cffi`) for the host OS and CPU architecture on which it runs.
- **Native Node addons (`sharp`) and macOS `.dmg` creation**: Require platform-native toolchains.

Using a **GitHub Actions matrix workflow** runs the Windows build on `windows-latest` and the macOS build on `macos-latest` in parallel, then publishes all artifacts to the release distribution repository (`WINDY-WINDWARD/blmterminal-binaries`).

---

## 2. Configuration Foundation Already in Place

The repository has been future-proofed so the same `electron-builder.json` and runtime code work unmodified on both Windows and macOS runners:

1. **`electron-builder.json`**:
   - `win.extraResources` bundles `backend/dist/blm-backend.exe` -> `blm-backend/blm-backend.exe`.
   - `mac.extraResources` bundles `backend/dist/blm-backend` -> `blm-backend/blm-backend`.
2. **`electron/main.js`**:
   - Dynamically selects `blm-backend.exe` on `win32` and `blm-backend` on `darwin`/`linux`.
3. **Platform Build Scripts**:
   - Windows: `npm run build:desktop` (uses `scripts/build_backend.ps1`)
   - macOS: `npm run build:desktop:mac` (uses `scripts/build_backend.sh`)

---

## 3. Required GitHub Repository Secrets

Before enabling the GitHub Actions workflow on `WINDY-WINDWARD/blm_terminal`, add the following secrets under **Settings -> Secrets and variables -> Actions**:

| Secret Name | Purpose |
|-------------|---------|
| `BINARIES_REPO_PAT` | A Fine-Grained Personal Access Token with `Contents: Read and write` permission on `WINDY-WINDWARD/blmterminal-binaries` (and `blmlanding` if cloning the signing script in CI). |
| `OTA_OFFLINE_KEY_JSON` | The full JSON contents of `ota-key-offline-DO-NOT-COMMIT.json` (used by `sign-ota-manifest.js` to sign OTA update manifests). |

*(Optional for macOS Gatekeeper Notarization later)*:
- `CSC_LINK` (Base64-encoded `.p12` Apple Developer ID Application certificate)
- `CSC_KEY_PASSWORD`
- `APPLE_ID`, `APPLE_APP_SPECIFIC_PASSWORD`, `APPLE_TEAM_ID`

---

## 4. GitHub Actions Workflow Blueprint (`.github/workflows/release.yml`)

Save the following workflow to `.github/workflows/release.yml` when ready to activate automated cloud builds:

```yaml
name: Build & Publish Desktop Release

on:
  push:
    tags:
      - 'v*'
  workflow_dispatch:

jobs:
  build:
    strategy:
      fail-fast: false
      matrix:
        include:
          - os: windows-latest
            platform: win
            build_cmd: npm run build:desktop
          - os: macos-latest
            platform: mac
            build_cmd: npm run build:desktop:mac

    runs-on: ${{ matrix.os }}

    steps:
      - name: Checkout blm_terminal
        uses: actions/checkout@v4

      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: '20'
          cache: 'npm'

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: 'pip'

      - name: Install Node dependencies
        run: npm ci

      - name: Install Python backend dependencies
        working-directory: ./backend
        run: |
          python -m pip install --upgrade pip
          pip install -e ".[dev]"
          pip install pyinstaller "camoufox==0.5.6"

      - name: Build Desktop Package (${{ matrix.platform }})
        run: ${{ matrix.build_cmd }}
        env:
          CSC_IDENTITY_AUTO_DISCOVERY: false

      - name: Sign OTA Manifest (Windows)
        if: matrix.platform == 'win' && env.OTA_Key_Present == 'true'
        shell: pwsh
        env:
          OTA_OFFLINE_KEY_JSON: ${{ secrets.OTA_OFFLINE_KEY_JSON }}
          OTA_Key_Present: ${{ secrets.OTA_OFFLINE_KEY_JSON != '' }}
        run: |
          $Pkg = Get-Content package.json | ConvertFrom-Json
          $Version = $Pkg.version
          $KeyPath = "$RUNNER_TEMP/ota-key.json"
          $env:OTA_OFFLINE_KEY_JSON | Set-Content -Path $KeyPath -NoNewline
          $ExeFile = Get-ChildItem -Path dist-desktop -Filter "*Setup*.exe" | Select-Object -First 1
          # If sign-ota-manifest.js is copied into scripts/sign-ota-manifest.js:
          if (Test-Path "scripts/sign-ota-manifest.js") {
            node scripts/sign-ota-manifest.js $Version $ExeFile.FullName $KeyPath "dist-desktop/ota-manifest"
          }
          Remove-Item $KeyPath -Force -ErrorAction SilentlyContinue

      - name: Upload Build Artifacts
        uses: actions/upload-artifact@v4
        with:
          name: desktop-artifacts-${{ matrix.platform }}
          path: |
            dist-desktop/*.exe
            dist-desktop/*.dmg
            dist-desktop/*.zip
            dist-desktop/*.yml
            dist-desktop/*.blockmap
            dist-desktop/ota-manifest.*

  publish:
    needs: build
    runs-on: ubuntu-latest
    steps:
      - name: Checkout blm_terminal (for package.json version)
        uses: actions/checkout@v4

      - name: Download All Platform Artifacts
        uses: actions/download-artifact@v4
        with:
          path: dist-all
          merge-multiple: true

      - name: Publish to WINDY-WINDWARD/blmterminal-binaries
        env:
          GH_TOKEN: ${{ secrets.BINARIES_REPO_PAT }}
        run: |
          VERSION=$(node -p "require('./package.json').version")
          TAG="v${VERSION}"
          REPO="WINDY-WINDWARD/blmterminal-binaries"

          if gh release view "$TAG" --repo "$REPO" >/dev/null 2>&1; then
            gh release upload "$TAG" dist-all/* --repo "$REPO" --clobber
          else
            gh release create "$TAG" dist-all/* --repo "$REPO" --title "BLM Terminal ${VERSION}" --notes "Release version ${VERSION}"
          fi
```

---

## 5. Developer Workflow Once Enabled

With the workflow above in place, any developer on any machine can trigger a full multi-OS release with two commands:

```bash
# 1. Bump version in package.json, commit, and tag
npm version patch   # or manually update version in package.json & git tag v2026.x.y

# 2. Push commit and tag to trigger GitHub Actions
git push && git push --tags
```

Or trigger it manually at any time via GitHub CLI:
```bash
gh workflow run release.yml
```
