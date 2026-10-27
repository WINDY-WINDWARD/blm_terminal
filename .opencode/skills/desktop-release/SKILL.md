---
name: desktop-release
description: Procedures for bumping, building, signing, verifying, and publishing official BLM Terminal desktop releases to GitHub Releases. Use for version bumps, release builds, OTA manifest signing, artifact checks, and publish:binaries/publish:desktop.
---

# Skill: BLM Desktop Release & Publishing Agent

**Description**: Procedures, cryptographic verification, and operational instructions for bumping, compiling, signing, and publishing official BLM Terminal desktop releases to GitHub Releases.

## Core Directives

1. **Strict Release Mode**:
   - Version bumps, tags, and production releases MUST use the sequential full build path (`npm run build:desktop`).
   - Fast builds (`npm run build:desktop:fast`) are strictly for local developer iteration; NEVER use fast builds for shipped releases.

2. **Artifact Hygiene**:
   - Before building, remove all prior `.exe`, `.blockmap`, `latest.yml`, and `ota-manifest.*` files from `dist-desktop/`.
   - Never leave an older version's installer in `dist-desktop/`, as signing the wrong installer will break client OTA updates.

3. **Mandatory Manual Verification**:
   - Every published release requires:
     1. `BLM Terminal Setup <version>.exe`
     2. `BLM Terminal Setup <version>.exe.blockmap`
     3. `latest.yml`
     4. `ota-manifest.json` (signed version payload matching the installer)
     5. `ota-manifest.sig` (detached Ed25519 signature generated with offline private key)
   - `npm run verify:release` is currently a **no-op stub** (`echo 'No verification script configured'`).
     It proves nothing. Verify the manifest, signature, and installer hash manually before uploading, and
     state exactly which checks you performed. If a real verifier is added later, update this directive.

4. **Environment & Network Clearance**:
   - Ensure local proxy variables (`HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, `GIT_HTTP_PROXY`, `GIT_HTTPS_PROXY`) are unset before running `gh` or `electron-builder` to avoid routing through dummy/discard ports.

## Standard Release Execution Checklist

```powershell
# 1. Bump version and create git release commit + tag
npm run release

# 2. Build full desktop installer from source
npm run build:desktop

# 3. Sign OTA manifest with offline private key
$pkg = Get-Content package.json | ConvertFrom-Json
$ver = $pkg.version
$exe = (Get-ChildItem dist-desktop -Filter "*$ver*.exe" | Where-Object { $_.Name -like "*Setup*" } | Select-Object -First 1).FullName
node ..\blmlanding\scripts\sign-ota-manifest.js $ver $exe ..\blmlanding\ota-key-offline-DO-NOT-COMMIT.json dist-desktop\ota-manifest

# 4. Verify hash and signature manually (verify:release is a no-op stub)
#    - confirm ota-manifest.json version/hash matches the .exe
#    - confirm ota-manifest.sig verifies with the bundled public key
#    - confirm latest.yml names the same version and installer

# 5. Publish to GitHub Releases (WINDY-WINDWARD/blmterminal-binaries)
npm run publish:binaries

# 6. Push release commit and tag
git push origin HEAD
git push origin refs/tags/v$ver
```
