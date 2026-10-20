# CLIProxyAPI Provider Management Implementation Plan

Date: 2026-10-20
Worktree: `C:\projects\blm_projects\blm_terminal\.worktrees\provider-management`
Branch: `feat/provider-management`

## Global Constraints

- Preserve BLM's chat agent, prompts, tools, `_run_tools_parallel`, SSE event schema, task routing, hunter/verifier behavior, Script Lab, and summaries.
- Keep one active route. CLIProxyAPI handles OAuth account selection, custom-endpoint key selection, retries, cooldowns, and session affinity within that route.
- Direct API-key providers and Copilot remain on their existing BLM paths.
- OAuth providers: `codex`, `antigravity`, `claude`, `xai`, `kimi`, `kimi-ai`, `meta`, `devin`.
- Route IDs: `oauth:<provider>`, `endpoint:<uuid>`, `direct:<provider>`.
- Public model IDs: `blm:<route_id>/<upstream_model>`. Parse at the first slash after `blm:`.
- Store `ai.provider`, `ai.hunter_model`, `ai.verifier_model`, and `ChatSession.model` using route-qualified IDs.
- Default routing strategy is `fill-first`. Sticky sessions default on. Per-account priority and weight remain guided controls.
- OAuth and custom endpoint secrets use an OS-keyring-backed AES-256-GCM vault. No plaintext fallback.
- Runtime proxy files are temporary, loopback-only, permission-restricted, and wiped after shutdown.
- The renderer never receives raw OAuth tokens, endpoint keys, proxy management keys, or client keys.
- No secret may appear in a URL query string, renderer response, log, diagnostic, or config read.
- Bundle official CLIProxyAPI v8.0.35 for Windows x64, macOS x64, and macOS arm64. No Windows ARM64.
- Existing repository style, black/amber Bento UI, and current Next/Electron architecture remain authoritative.
- Never work outside the isolated worktree. Commit each task on `feat/provider-management`.

## Task 1: Vault, route registry, and persistence foundation

### Deliverables

- Add `keyring` and `psutil` dependencies to `backend/pyproject.toml`.
- Add PyInstaller collection/hidden-import support for keyring backends in both backend build scripts.
- Add SQLAlchemy models and one Alembic migration for:
  - `ai_provider_routes`: route ID, kind, provider, display label, proxy prefix, enabled, config JSON, timestamps.
  - `ai_provider_credentials`: credential ID, route ID, kind, vault reference, proxy credential name, masked label/identity, priority, weight, enabled, status, cooldown, last redacted error, timestamps.
- Seed the eight OAuth routes idempotently with stable prefixes `blm-<first 16 hex of sha256(route_id)>`.
- Implement a versioned vault service:
  - AES-256-GCM using `cryptography`.
  - 32-byte key retrieved by Python keyring under service `blm-terminal-provider-vault`, account `v1`.
  - Atomic write, in-process async lock, restrictive file permissions.
  - Entries for OAuth auth JSON, endpoint headers, endpoint keys, and cooldown snapshots.
  - Explicit `available`, `keyring_unavailable`, and `vault_corrupt` states.
- Implement central route/model helpers:
  - Resolve active route from `ai.provider` plus schema defaults.
  - Normalize legacy provider IDs.
  - Format and parse route-qualified model IDs.
  - Map legacy model strings to the current route.
  - Validate that a model belongs to the active route.
- Add backend tests covering keyring signatures through monkeypatching, vault round-trip/corruption/atomic replacement, route seeding, route/model parsing including slash-containing model IDs, and legacy mappings.

### Acceptance

- `pytest` for new services passes.
- Existing `tests/test_multi_provider_offline.py` and `tests/test_security_guards.py` still pass.
- No secret is written to application logs by the vault or registry helpers.

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

## Task 3: Route-aware inference, model catalog, and legacy migration

### Deliverables

- Refactor `ai_config.py` around active-route resolution while preserving direct-provider key lookup and Copilot behavior.
- Refactor `llm_provider.py`:
  - Parse route-qualified models.
  - Route OAuth and custom endpoints through the local proxy's OpenAI-compatible `/v1/chat/completions`.
  - Keep the existing generic tool loop and SSE contract.
  - Add `X-Session-Id` for chat, workers, summaries, and one-off calls.
  - Suppress BLM's own 429 retry loop for proxy-backed requests.
  - Capture `X-CPA-TRACE-ID` into a bounded in-memory diagnostic ring.
- Remove active hand-rolled Codex and Antigravity request loops and old auth routers from normal runtime. Keep standalone read-only migration helpers.
- Add migration logic:
  - Map legacy provider IDs and worker/chat model strings.
  - Import legacy Codex tokens into an encrypted OAuth credential before any new refresh; clear old DB tokens only after successful import.
  - Attempt Antigravity import only with sufficient credential fields; otherwise mark re-login required and leave the old file untouched.
- Replace active-route model fetching with route-qualified catalogs:
  - OAuth union from `/credentials/models` cached in the route row.
  - Custom endpoint models from the stored model list.
  - Direct provider catalogs through existing direct-provider fetchers.
- Replace `GET /provider-models?api_key=...` with `POST /provider-models` taking the temporary key in the JSON body.
- Ensure `/chat/models` and `/ai/status` return the route-qualified active catalog and route health.
- Add tests for route parsing, direct-provider regression, legacy migrations, model-catalog caching, proxy URL/model construction, session headers, trace parsing, and no key in request URLs.

### Acceptance

- Direct providers and Copilot still stream through their existing paths.
- OAuth/custom routes reach the local proxy with `${prefix}/${upstream_model}`.
- Old tests that depended on the removed Codex Responses adapter are replaced with proxy-loop tests, not skipped.

## Task 4: Provider management API

### Deliverables

- Add an authenticated FastAPI router for the approved provider APIs:
  - `GET /ai/routes`
  - `POST /ai/routes/{route_id}/activate`
  - `PATCH /ai/routes/settings`
  - OAuth start/poll/cancel with optional `replace_account_id`
  - Account patch, refresh, test, reauth, reset cooldown, and remove
  - Custom endpoint create/update/delete, key CRUD, model preview/refresh, and test
  - Provider diagnostics with bounded, non-content trace data
  - Explicit provider-only vault reset
- Validate custom endpoint input:
  - HTTP(S) only.
  - Reject userinfo, malformed URLs, non-HTTP schemes, header injection, and cloud metadata hosts.
  - Accept public, private, and localhost addresses with warning flags.
  - Keep header values and keys vault-only and return masked summaries.
- Implement OAuth session reconciliation:
  - Device and browser flows.
  - Pending-session expiry/cancel.
  - Match reauth by provider identity; replace existing account only on identity match, otherwise add new account with a notice.
  - Never log callback query strings or token payloads.
- Ensure all route responses are redacted and include route health, account/key summaries, model catalog, active state, and recovery state.
- Add API tests for every action, validation path, OAuth expiry/cancel, redaction, keyring degradation, and reset scoping.

### Acceptance

- Direct-provider state remains readable and usable while proxy storage is unavailable.
- No endpoint returns raw credentials or proxy management configuration.
- API tests cover failure paths, not only happy paths.

## Task 5: Security redaction and server-only OpenAlgo credentials

### Deliverables

- Define the secret-key set for direct AI keys, OpenAlgo, Copilot, Claude Code, and legacy Codex tokens.
- Make `GET /system-config` omit raw secret values and return configured flags.
- Make secret `PUT` responses omit the submitted value.
- Add a server-only OpenAlgo credential endpoint protected by a separate internal token shared only by Electron, Next, and Python. Ensure the Next catch-all cannot forward a browser-supplied internal token.
- Update `src/lib/openalgo-server.ts`, OpenAlgo health, and ws-token routes to use the internal endpoint.
- Update direct-provider UI data contracts so a configured key is shown as configured/replaceable rather than prefilled.
- Add tests asserting sentinel secrets never appear in renderer responses, request URLs, logs, or error payloads.

### Acceptance

- `openalgo.api_key` remains usable by server-side Next routes.
- Browser-visible configuration contains no secret values.
- Existing direct key save behavior works through explicit PUT.

## Task 6: Unified provider modal and OAuth account management UI

### Deliverables

- Add a shared `AiProvidersModal` with the three approved tabs and black/amber Bento styling.
- Top summary: active route, proxy health, vault recovery, routing strategy, sticky-session toggle, account/key count.
- Implement `OAUTH ACCOUNTS`:
  - Eight provider groups.
  - Account cards with identity, status/cooldown, priority, weight, enable, refresh, reauth, test, reset-cooldown, remove.
  - Device-code and browser flows, pending/cancel/expiry states.
  - Reauth mismatch notice.
- Add route activation and React Query cache invalidation for provider route/status/catalog changes.
- Add vault recovery/reset UI that leaves direct providers usable.
- Open the modal from Settings and an explicit `PROVIDERS` command.
- Add Vitest coverage for tab rendering, OAuth states, account actions, activation, and recovery.

### Acceptance

- All account controls are keyboard-accessible and use existing modal primitives where available.
- No secret appears in component props, DOM, or browser requests.
- UI tests cover pending, error, disabled, cooldown, and recovery states.

## Task 7: Custom endpoints, direct providers, and model-selector integration

### Deliverables

- Implement `CUSTOM ENDPOINTS`:
  - Add/edit/delete route.
  - Base URL and optional secret headers.
  - Multiple weighted keys with enable/test/remove.
  - Model fetch, selectable model list, and manual fallback.
  - URL warning/error presentation.
  - Route activation and endpoint test.
- Implement `DIRECT PROVIDERS` using existing instructions and model-fetch controls, with configured-key indicators and replace-key flow.
- Refactor `SettingsModal` and `FirstLaunchModal` to reuse the shared provider components instead of duplicated Codex/Antigravity OAuth code.
- Update AiWidget, hunter, verifier, summaries, and Script Lab model selectors to use route-qualified catalogs.
- Automatically remap stale model selections to the first valid model for the active route; invalidate relevant query caches on all provider/account/key/catalog changes.
- Add frontend tests for endpoint CRUD, key controls, direct-provider behavior, stale model remapping, and FirstLaunch/Settings integration.

### Acceptance

- Active-route model lists never contain IDs from another route.
- Switching route does not leave a sendable invalid model.
- Direct provider setup remains functionally equivalent to the current behavior.

## Task 8: Documentation, release assets, and end-to-end verification

### Deliverables

- Document provider management, migration behavior, keyring recovery, routing semantics, and custom endpoint security.
- Add the CLIProxyAPI MIT notice and pinned release provenance.
- Add an integration test harness using a fake OpenAI-compatible upstream to prove custom endpoint multi-key failover and tool-call continuation through the proxy.
- Add a mocked proxy test proving OAuth account priority/weight selection, sticky session headers, cooldown restore, and trace attribution.
- Add a manual live-account checklist for Codex function and parallel tool calls; do not require live accounts in CI.
- Run backend focused tests, npm tests, TypeScript build, backend build, and desktop packaging checks for the current platform.
- Verify no generated runtime secrets remain after clean shutdown and no secret appears in release-facing files.

### Acceptance

- All automated suites and builds pass on Windows x64.
- Packaging includes the correct CLIProxyAPI binary and notice and fails closed on checksum mismatch.
- The final branch contains no temporary research files or plaintext test credentials.

## Review Requirements

- Each task must be implemented by one fresh implementer, then reviewed for spec compliance and code quality.
- Fix the task before starting the next task when the review finds Critical/Important issues.
- Run a final whole-branch review after Task 8 and resolve or park every finding with a ledger ruling.
