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

3. **Mandatory Verification Gate**:
   - Every published release requires exactly five assets:
     1. `BLM Terminal Setup <version>.exe`
     2. `BLM Terminal Setup <version>.exe.blockmap`
     3. `latest.yml`
     4. `ota-manifest.json` (signed version payload matching the installer)
     5. `ota-manifest.sig` (detached Ed25519 signature generated with the offline private key)
   - `npm run verify:release` is a real gate (`scripts/verify_release.js`): it checks the
     Ed25519 signature, the manifest↔installer sha256/size, `latest.yml` consistency, and that no
     stale installer from another version sits in `dist-desktop/`. It reuses `electron/ota.js`, the
     same module the shipped client verifies with, so the gate cannot drift from the updater.
   - `npm run publish:binaries` runs the gate itself and refuses to publish on any failure, then
     confirms the release carries exactly the five expected assets.
   - `npm run verify:release:live` re-checks the published feed (and with `--binary` re-downloads the
     installer and hashes it). Run it once the portal cache expires (~5 min).

4. **Client-side verification is fail-closed**:
   - `electron/ota.js` holds `OTA_PUBLIC_KEYS`; a downloaded installer that does not match the signed
     manifest is never staged for install, and the app reports "automatic updates are disabled" if the
     verifier cannot load at all.
   - `scripts/publish_binaries.ps1` also launches `dist-desktop\win-unpacked\BLM Terminal.exe --verify-ota`
     before uploading. That proves libsodium survives asar packaging; a failure there would otherwise
     dark every future update. Never bypass it.

5. **Environment & Network Clearance**:
   - Ensure local proxy variables (`HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, `GIT_HTTP_PROXY`, `GIT_HTTPS_PROXY`) are unset before running `gh` or `electron-builder` to avoid routing through dummy/discard ports.

## Standard Release Execution Checklist

```powershell
# 1. Bump version and create git release commit + tag
npm run release

# 2. Build full desktop installer from source (sequential; never the fast path)
npm run build:desktop

# 3. Sign OTA manifest with the offline private key (operator step, never automated)
$pkg = Get-Content package.json | ConvertFrom-Json
$ver = $pkg.version
$exe = (Get-ChildItem dist-desktop -Filter "*$ver*.exe" | Where-Object { $_.Name -like "*Setup*" } | Select-Object -First 1).FullName
node ..\blmlanding\scripts\sign-ota-manifest.js $ver $exe ..\blmlanding\ota-key-offline-DO-NOT-COMMIT.json dist-desktop\ota-manifest

# 4. Verify locally — hard gate, 17 checks
npm run verify:release

# 5. Push the release commit and tag BEFORE publishing. `gh release create`
#    otherwise creates the remote tag on the remote default branch.
git push origin HEAD
git push origin refs/tags/v$ver

# 6. Publish the five artifacts to GitHub Releases (WINDY-WINDWARD/blm_terminal).
#    Re-runs the gate, checks the tag is pushed, runs --verify-ota, then uploads.
#    Pass -Build only if you deliberately want a fresh (unsigned) rebuild first.
npm run publish:binaries

# 7. Confirm the portal serves the release (wait out the 5-minute cache)
npm run verify:release:live
```

## Updater architecture (why the ordering matters)

- `electron/updater.js` owns the authoritative update state (phase, percent, verification, staged
  installer, pending-install marker). It persists to `userData/updater-state.json` and is queryable
  through `get-updater-state`, so a renderer reload or app restart cannot lose a staged update.
- `electron/main.js` wires that controller to `autoUpdater`; `src/lib/updaterStore.ts` is the single
  renderer store (hydrated once, then fed by `updater-message` broadcasts). `UpdateModal` and
  Settings → System read the same snapshot.
- `install-update` re-hashes the staged installer, kills the backend and the CLIProxyAPI sidecar
  gracefully, writes `pending-install.json`, and only then calls `quitAndInstall`. If the installer
  never applies, the next launch reports it instead of silently retrying.
- A release whose manifest does not verify makes every client refuse the update — treat a failed
  `verify:release` as a stop-the-line event, not a warning.

