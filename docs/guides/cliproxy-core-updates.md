# CLIProxyAPI Core Updates

## 1. Overview
The CLIProxyAPI core is an independently updated component.
The application release does not decide the core version.
The background worker checks for newer core versions and downloads them automatically.

## 2. Layout
The system stores the core files in the per-user core root directory.
Set the `CLIPROXY_CORE_ROOT` environment variable to change this path.
If this variable is not set, the core root defaults to the `cliproxy-core` folder next to the database file.

The core root contains four directories and one state file:
- `install`: Holds the currently active core binary and its `metadata.json` file.
- `staging`: Holds downloaded and extracted versions that wait for promotion.
- `download`: Holds temporary archive files and checksum files during download.
- `rollback`: Holds the previous working installation for recovery.
- `update-state.json`: Stores check timestamps, pending version, quarantine list, and last error.

The `metadata.json` file inside `install` stores the version, the asset name, the installation timestamp, and the source of the active core.

## 3. Update Flow
A background worker executes a daily check for upstream releases.
The worker queries GitHub API, GitHub Atom feeds, or GitCode mirrors to discover new versions.
When a newer version exists, the worker downloads the platform-specific release archive.
The worker verifies the archive SHA-256 against the GitHub release asset digest.
The worker then cross-checks the hash against upstream `checksums.txt`.
The worker extracts the archive safely to the `staging` directory.
At the next application start, the startup pipeline promotes the staged core to `install`.
Users can also trigger manual activation through the HTTP API without restarting the application.

## 4. Trust Model
The updater enforces strict verification rules before executing any binary:
- **HTTPS Only**: All download requests use encrypted HTTPS connections.
- **Asset Digest Verification**: The archive SHA-256 must match the digest published in GitHub release metadata.
- **Checksums Cross-Check**: The updater validates the archive against the upstream `checksums.txt` file when present.
- **Safe Extraction**: The archive extractor blocks path traversal attacks and rejects entries with parent directory references.
- **Minimum Supported Version**: The system rejects releases older than version 8.0.39.
- **Quarantine**: If a promoted core fails to start, the system quarantines that version to prevent future installation attempts.

## 5. Rollback
The `rollback` directory retains the previous known-working binary.
If a newly promoted core fails the readiness check during startup, the supervisor triggers an automatic rollback.
The supervisor moves the backup files from `rollback` back into `install`.
Users can also invoke manual rollback at any time through the HTTP API.

## 6. Configuration
Operators configure update behaviour through `system_config` database keys:
- `cliproxy.auto_update`: A boolean value that controls background update checks. Set to `true` to enable automatic checks.
- `cliproxy.download_mirrors`: A comma separated list of HTTPS base URLs. The updater tries each mirror before the direct GitHub URL.

## 7. HTTP API
The backend exposes five management endpoints under `/api/cliproxy`:
- `GET /api/cliproxy/status`: Returns current core version, update state, supervisor status, and available updates.
- `POST /api/cliproxy/check`: Triggers an immediate check for upstream releases and stages an update if available.
- `POST /api/cliproxy/install`: Downloads and stages a specified version from upstream releases.
- `POST /api/cliproxy/activate`: Promotes a staged core version to the active installation directory immediately.
- `POST /api/cliproxy/rollback`: Restores the previous core version from the rollback directory.

## 8. Troubleshooting

| Symptom | Cause |
|---|---|
| The core does not update | The setting `cliproxy.auto_update` is false or the target version is in the quarantine list. |
| The update is staged but does not activate | The application has not restarted or the staged binary failed permissions and integrity checks. |
| The core rolled back | The promoted core binary crashed during startup or failed the supervisor readiness probe. |
| The download fails | Network connectivity failed, GitHub rate limits blocked requests, or archive checksums mismatched. |
