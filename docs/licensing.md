# BLM Terminal Licensing

This document describes how the Electron desktop client enforces licensing.

## 1. The Gate

Licensing is enforced entirely within the Electron Main process (`electron/main.js`). The `startApp()` function halts and displays a license entry window if no valid license is found. The Python backend and Next.js frontend are **not spawned** until the license gate is passed.

### The Per-Launch Token

To prevent users from bypassing the gate by running the backend or frontend directly, or from other local processes interacting with the local APIs:
1. Electron generates a random 32-byte token after passing the gate.
2. The token is passed to the Python and Next.js child processes via stdin/IPC (never argv or env vars, which are visible in process listings).
3. Both servers bind `127.0.0.1` on **ephemeral (random) ports** and report their port back to Electron.
4. Both servers reject any request lacking the `x-blm-token` header (401/403) and validate the `Host` header (DNS rebinding protection).
5. Electron injects the token into outgoing browser requests using `session.defaultSession.webRequest.onBeforeSendHeaders`, scoped strictly to the local origins.

## 2. Re-Validation Loop

Once running, the client re-validates the license every 6 to 12 hours (randomized jitter).
- If the result is `ok`, the offline lease is updated.
- If the result is indeterminate (network down, rate limited), the client continues running silently.
- If the result is a definitive denial (`revoked`, `expired`, `unknown`), the client shows a warning dialog, allows the user 5 minutes to save their work, and then quits. **It never modifies or deletes user data.**

## 3. Offline Leases and Reinstalls

A valid response from the server includes an Ed25519-signed lease valid for 7 days.
- The lease is bound to the specific `iid` (Install UUID) of that terminal instance.
- Copying the `license.dat` file to another computer will fail the `iid` check, forcing the new computer to perform an online check (which increments the server's abuse counters).
- A legitimate reinstall generates a new `iid`, performs one online check, and then receives a new lease, running offline for 7 days.

## 4. OTA Verification Flow

The updater checks for updates before any license deny/quit path runs, ensuring locked-out users can still receive bug fixes.
Because the installer uses unsigned NSIS, the client performs strict manifest verification:
1. The client fetches `ota-manifest.json` and its signature (`ota-manifest.sig`) over HTTPS.
2. The signature is verified against a list of baked-in offline public keys.
3. The client verifies the version is strictly monotonic (no downgrades).
4. The client downloads the `.exe` installer.
5. **Before calling `quitAndInstall`**, the client hashes the `.exe` and verifies it matches the SHA-256 hash in the signed manifest. Any mismatch cancels the installation and deletes the file.
