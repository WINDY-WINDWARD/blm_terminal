## Task 2: CLIProxyAPI packaging, supervisor, and lifecycle

### Deliverables

- Add pinned CLIProxyAPI download/staging scripts for Windows and macOS:
  - v8.0.35 assets and SHA-256 verification.
  - Stage the selected architecture at `vendor/cliproxyapi/runtime/cliproxyapi(.exe)`.
  - Fail the build if the binary is absent or checksum-mismatched.
- Add electron-builder `extraResources` under `resources/cliproxyapi`, architecture-aware executable resolution, and an MIT notice plus third-party provenance file.
- Add a FastAPI `ProxySupervisor`:
  - Lazy start after vault availability.
  - Loopback-only ephemeral port; random client and management keys.
  - Runtime directory under app data, mode 0700; files mode 0600.
  - Generate config with `allow-remote: false`, control panel disabled, `force-model-prefix: true`, `save-cooldown-status: true`, configured strategy, sticky sessions, and vetted retry defaults.
  - Materialize OAuth auth JSON from the vault and cooldown `.cds` snapshots before start.
  - Readiness polling through `/healthz`, bounded restart/backoff, crash state reporting, and stale-process cleanup using `psutil`.
  - Sync refreshed auth JSON and `.cds` files back to the vault on account/refresh changes, debounced request completion/error, and shutdown.
  - Delete the runtime directory after graceful shutdown; detect and remove stale runtime directories at startup.
- Add a redacted internal management client for `/v8/management` that never exposes config or credential payloads outside backend services.
- Add an admin-only graceful shutdown endpoint. Update Electron to call it before force-killing Python if available.
- Pass only non-secret path/configuration values such as `CLIPROXY_BIN` and runtime root to Python. Never pass the vault key or management key through argv.
- Add tests for asset manifest/checksum logic where practical, config generation redaction, runtime permissions, lifecycle readiness/restart, cooldown restore, auth sync, graceful cleanup, and stale runtime cleanup.

### Acceptance

- Build scripts reject a missing or modified sidecar.
- Unit tests prove generated config contains required routing flags and no secret-bearing values leak into renderer-facing responses.
- Mocked supervisor tests prove lazy start, restart, shutdown cleanup, and stale-directory removal.

