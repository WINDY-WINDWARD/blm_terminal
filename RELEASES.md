# BLM Terminal — Release & Upgrade Guide

This document outlines the release philosophy, versioning specification, release cadences, and developer procedures for publishing updates to BLM Terminal.

---

## 1. Versioning Specification: `YYYY.M.B`

BLM Terminal follows a calendar-and-build versioning scheme that complies strictly with Semantic Versioning (SemVer) requirements:

$$\text{Format: } \mathbf{YYYY.M.B}$$

*   **`YYYY`**: Full calendar year (e.g., `2026`).
*   **`M`**: Current month without leading zero (e.g., `9` for September, `10` for October). *Leading zeros (e.g., `09`) are forbidden by SemVer and will fail during packaging.*
*   **`B`**: Monotonically incrementing build number within that month (e.g., `1`, `2`, `3`).

**Examples**:
*   `2026.9.1` — First release of September 2026.
*   `2026.9.2` — Second release / patch in September 2026.
*   `2026.10.1` — First release of October 2026 (build counter resets to 1).

---

## 2. When to Release a New Version

Releases should be published under the following circumstances:

1.  **Feature Additions / Milestones**:
    *   New widgets (e.g., new scanners, order types, AI summarizers).
    *   Significant terminal UI/UX updates or performance optimizations.
2.  **Bug Fixes & Hotfixes**:
    *   Resolving critical operational issues (e.g., authentication freezes, WebSocket drops, NSE rate limiter adjustments).
3.  **Routine Stable Releases**:
    *   End-of-sprint or monthly cumulative updates consolidating enhancements and dependency patches.

---

## 3. How to Release a New Version (Step-by-Step)

The entire version-bumping, Git tagging, binary compilation, and GitHub Release deployment process is automated.

### Prerequisites:
*   Your working tree on the target branch (e.g., `main`) must be committed.
*   All tests and Next.js builds must pass (`npm test && npm run build:next`).

### Step 1: Run the Automated Version Bump Script
In your terminal, execute:
```bash
npm run release
```
This script will:
1.  Read the current year and month.
2.  Increment the build number or reset it if a new month has begun.
3.  Update `version` in `package.json`.
4.  Create a Git commit: `chore(release): vYYYY.M.B`.
5.  Create a Git tag: `vYYYY.M.B`.

### Step 2: Push Commits and Tags to GitHub
Push your commits and the new tag upstream:
```bash
git push origin HEAD --follow-tags
```

### Step 3: Automated CI/CD Compilation & Publishing
Once the tag `v*` is pushed:
1.  GitHub Actions automatically triggers the workflow defined in `.github/workflows/release.yml`.
2.  The runner installs Python, sets up PyInstaller, and compiles `blm-backend.exe`.
3.  The runner builds the Next.js production bundle.
4.  `electron-builder` packages the Windows NSIS installer and publishes:
    *   `BLM Terminal Setup <version>.exe`
    *   `latest.yml` (checksum and update metadata)
    directly to a new GitHub Release at `https://github.com/WINDY-WINDWARD/blm_terminal/releases`.

*Note:* For `electron-builder` to publish successfully, GitHub Actions uses the built-in `GITHUB_TOKEN`. Make sure the Actions settings for the repository allow "Read and write permissions".

---

## 4. How Users Receive Upgrades (Client Auto-Update)

BLM Terminal includes client-side OTA (Over-The-Air) update integration via `electron-updater`:

1.  **Silent Update Detection**: When a user launches the installed BLM Terminal desktop app, `electron/main.js` waits 5 seconds and then silently checks the GitHub repository for new releases via `latest.yml`.
2.  **Background Download**: If a newer version is found, the application downloads the update package in the background.
3.  **Manual Checks & Prompting**: Users can open the **Settings** widget and click **"CHECK FOR UPDATES"** to manually initiate a check. The UI will reflect the current updater status (Checking, Downloading, Ready).
4.  **Installation**: 
    *   Once the download completes, a glowing **"INSTALL & RESTART"** button will appear in the Settings widget.
    *   Clicking this button cleanly terminates child processes (`server.js` and `blm-backend.exe`) and launches the NSIS installer to apply the update.
    *   If the user quits the application normally while an update is staged, the update will automatically apply on quit (`autoInstallOnAppQuit: true`).

---

## 5. Local Production Mode Testing (Before Release)

If Next.js Turbopack dev mode hangs on your machine, you can run and test the complete desktop application against the production Next.js build locally:

```bash
# 1. Build the Next.js production bundle
npm run build:next

# 2. Compile the backend executable (if not already built)
npm run build:backend

# 3. Launch Electron in production mode
npm run electron:prod
```
