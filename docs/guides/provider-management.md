# BLM Terminal: Provider Management & Routing Architecture

> **Status:** Implemented (Tasks 1–8).  
> **Scope:** Unified AI provider routing, CLIProxyAPI sidecar supervisor, OS keyring-backed encryption, custom OpenAI-compatible endpoints, OAuth account rotation, and legacy migration.

---

## 0. Architectural Principles & Decisions

| Area | Decision | Rationale |
|---|---|---|
| **Active Route Policy** | **Strictly one active route** at any given moment | Eliminates prompt/tool divergence across models; ensures predictable execution context for chat agents, hunter/verifier workflows, and Script Lab. |
| **Model Namespacing** | `blm:<route_id>/<upstream_model>` | Fully disambiguates models across route families, prevents collision between upstream models of the same name, and preserves auditability. |
| **Secret Storage** | **OS Keyring + AES-256-GCM** | Master key stored in platform credential manager (Windows Credential Manager, macOS Keychain, Linux SecretService); secrets encrypted in an isolated vault (`provider_vault.enc`). **Zero plaintext fallback**. |
| **Proxy Supervision** | **Ephemeral sidecar (CLIProxyAPI v8.0.35)** | Managed purely by `ProxySupervisor` on loopback `127.0.0.1` on an ephemeral port. Wiped on shutdown. Direct providers bypass proxy. |
| **Security Boundaries** | **Zero secret leakage** | No secrets in query strings, URLs, renderer responses, logs, diagnostics, or configuration dumps. Strict redaction (`[REDACTED]`). |
| **Packaging & Licensing** | **Pinned v8.0.35 release binary** | Embedded with upstream MIT license notice in `resources/cliproxyapi/` and `electron-builder.json`. Fails closed on checksum mismatch. |

---

## 1. Route Families & Model Identification

BLM Terminal supports three distinct route families. Every model in the application is identified by a globally unique URI conforming to `blm:<route_id>/<upstream_model>`.

```
                    ┌───────────────────────────────────────────────┐
                    │               Active Route                    │
                    └──────────────────────┬────────────────────────┘
                                           │
         ┌─────────────────────────────────┼────────────────────────────────┐
         │                                 │                                │
         ▼                                 ▼                                ▼
┌─────────────────┐             ┌─────────────────────┐          ┌──────────────────────┐
│  oauth:<prov>   │             │   endpoint:<uuid>   │          │    direct:<prov>     │
├─────────────────┤             ├─────────────────────┤          ├──────────────────────┤
│ • 8 OAuth provs │             │ • Custom OpenAI-    │          │ • direct:zen-free    │
│   codex,claude, │             │   compatible gateway│          │ • direct:openrouter  │
│   xai,kimi,etc. │             │ • Multi-key pool    │          │ • direct:groq        │
│ Via CLIProxyAPI │             │ • Custom headers    │          │ • direct:openai      │
│ sidecar proxy   │             │                     │          │ • direct:anthropic   │
│ (session affinity             │ Via CLIProxyAPI     │          │ • direct:gemini      │
│  & cooldowns)   │             │ sidecar proxy       │          │ • direct:copilot     │
└────────┬────────┘             └──────────┬──────────┘          └──────────┬───────────┘
         │                                 │                                │
         └────────────────┬────────────────┘                                │
                          ▼                                                 ▼
             ┌─────────────────────────┐                       ┌────────────────────────┐
             │ CLIProxyAPI Sidecar     │                       │ Native BLM Provider    │
             │ (127.0.0.1:ephemeral)   │                       │ (Direct HTTPS Client)  │
             └────────────┬────────────┘                       └────────────┬───────────┘
                          ▼                                                 ▼
               Upstream AI Gateways                               Upstream AI Gateways
```

### 1.1 `oauth:<provider>` (CLIProxyAPI Sidecar)
- **Route ID Format:** `oauth:<provider>` (e.g. `oauth:codex`, `oauth:antigravity`, `oauth:claude`, `oauth:xai`, `oauth:kimi`, `oauth:kimi-ai`, `oauth:meta`, `oauth:devin`).
- **Target Providers:** All supported OAuth services: `codex`, `antigravity`, `claude`, `xai`, `kimi`, `kimi-ai`, `meta`, `devin`.
- **Execution Path:** Routes through the local CLIProxyAPI sidecar.
- **Model URI Example:** `blm:oauth:codex/gpt-4o`, `blm:oauth:antigravity/claude-3-5-sonnet`.
- **Capabilities:** Multi-account rotation, automatic OAuth refresh token handling, priority/weight assignment, cooldown timers on rate limits.

### 1.2 `endpoint:<uuid>` (Custom OpenAI-Compatible Endpoints)
- **Route ID Format:** `endpoint:<uuid>` (e.g. `endpoint:550e8400-e29b-41d4-a716-446655440000`).
- **Target Providers:** Private vLLM, Ollama, LiteLLM, OpenRouter, Together AI, Azure OpenAI, or self-hosted model gateways.
- **Execution Path:** Routes through CLIProxyAPI configured via `openai-compatibility` blocks.
- **Model URI Example:** `blm:endpoint:550e8400-e29b-41d4-a716-446655440000/llama-3.3-70b-instruct`.
- **Capabilities:** Weighted multi-key pool with automatic 401/429 failover, custom HTTP headers, prefix isolation.

### 1.3 `direct:<provider>` (Native Direct Provider Execution)
- **Route ID Format:** `direct:<provider>` (e.g. `direct:zen-free`, `direct:openrouter`, `direct:groq`, `direct:openai`, `direct:anthropic`, `direct:gemini`, `direct:copilot`).
- **Execution Path:** **Bypasses CLIProxyAPI entirely.** Requests are executed directly by `backend/app/services/llm_provider.py` using native asynchronous HTTP clients.
- **Model URI Example:** `blm:direct:openrouter/anthropic/claude-3.5-sonnet`, `blm:direct:zen-free/zen-default`.
- **Copilot Path:** GitHub Copilot remains on BLM's dedicated token and API path.

---

## 2. OAuth Account Management via CLIProxyAPI

OAuth routes allow users to connect multiple accounts per provider. The CLIProxyAPI sidecar manages token refresh, account switching, and rate limit cooldowns.

### 2.1 Account Lifecycle & Authorization
1. **Initiation:** Client calls `POST /api/ai/routes/oauth/start` with JSON body `{"provider": "<provider>"}`. The backend queries CLIProxyAPI's `/v8/management/oauth/auth-url` to generate a state token and browser authorization URL.
2. **Browser Auth:** User approves access in their web browser.
3. **Callback Submission:**
   - **Local Callback:** CLIProxyAPI captures the loopback redirect on its dedicated OAuth port.
   - **Manual Callback:** In headless or restricted environments, the user inputs the authorization code or redirect URL in the `OAuthSessionDialog`. The client submits this via `POST /api/ai/routes/oauth/callback`.
4. **Polling & Reconciliation:** The client polls `GET /api/ai/routes/oauth/poll?state={state}`. Once authenticated, the credential tokens are encrypted in `ProviderVault`, CLIProxyAPI's configuration is updated, and the account status is set to `active`.
5. **Cancellation:** Unfinished sessions are cancelled via `POST /api/ai/routes/oauth/cancel` with JSON body `{"state": "<state>"}`, preventing leaked state in CLIProxyAPI.

### 2.2 Account Selection Policies & Sticky Sessions
- **Priority & Weight:** Each account has an integer `priority` (lower numbers tried first) and `weight` (proportional distribution among same-priority accounts). These can be patched via `PATCH /api/ai/routes/accounts/{account_id}`.
- **Session Affinity (`X-Session-Id`):**
  - BLM generates and sends a sticky session header `X-Session-Id: {session_id}` on every inference request through the proxy.
  - CLIProxyAPI enforces `session-affinity: true` with `session-affinity-ttl: "1h"`. All turns within a multi-turn chat session stick to the same upstream account, preventing context fragmentation and session thrashing.
- **Cooldown Handling:**
  - When an account receives a 429 (Rate Limit) or 401 (Auth Expired), CLIProxyAPI places the credential into cooldown.
  - Cooldown states are backed up into the `ProviderVault` cooldown snapshot table (`save-cooldown-status: true`).
  - **Manual Cooldown Reset:** Users can clear an account's cooldown immediately using `POST /api/ai/routes/accounts/{account_id}/reset-cooldown`. This invokes CLIProxyAPI's `/v8/management/routing/cooldown/reset` and removes the snapshot from the vault.

---

## 3. Custom Endpoint Setup & Security

Custom endpoints provide connectivity to any OpenAI-compatible HTTP inference gateway while enforcing strict client-side security policies.

### 3.1 URL Validation & Warning Signals
During creation or modification (`POST /api/ai/routes/endpoints` or `PATCH /api/ai/routes/endpoints/{endpoint_id}`), URLs are rigorously validated:
- **Hard Rejection:** Schemes other than `http` or `https` are immediately rejected with HTTP 422. Missing hostnames or port violations fail closed.
- **Advisory Security Warnings (`warnings: string[]`):**
  - **Unencrypted HTTP:** Emits a warning that credentials and prompts will travel in plaintext over remote networks.
  - **Loopback / Localhost (`127.0.0.1`, `localhost`):** Reminds the user that the target service must run on the local machine and not inside an isolated container.
  - **Private / RFC 1918 Networks (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `100.64.0.0/10`):** Alerts the user that they are targeting internal network resources, warning against DNS rebinding and internal network exposure.

### 3.2 Header Handling & Override Rules
- Users can define custom key-value headers (e.g. `HTTP-Referer`, `X-Title`, `OpenAI-Organization`).
- **Sensitive Header Masking:** Any header whose name matches `authorization`, `api-key`, `token`, `secret`, `cookie`, or `key` is stored encrypted in `ProviderVault` and displayed as `[REDACTED]` in UI and API outputs.
- **Override Safeguards:** The `Authorization` header is automatically managed by the multi-key pool and cannot be overwritten by static headers.

### 3.3 Weighted Multi-Key Pool & Automatic Failover
Custom endpoints support multiple API keys with independent priorities and weights:
```yaml
openai-compatibility:
  - name: "my-vllm-cluster"
    prefix: "endpoint-a1b2c3d4-..."
    base-url: "https://llm.internal.corp/v1"
    headers:
      "X-Client": "BLM-Terminal"
    models:
      - name: "llama-3.3-70b-instruct"
    api-key-entries:
      - api-key: "sk-primary-key"
        priority: 1
        weight: 1
      - api-key: "sk-secondary-backup-key"
        priority: 2
        weight: 1
```
- **Failover Mechanism:** When the primary key returns HTTP 401 (Unauthorized) or HTTP 429 (Rate Limit), CLIProxyAPI automatically marks the key in cooldown and retries the request using the secondary key without dropping the stream or returning an error to the user.

---

## 4. Keyring Storage & Secret-Handling Guarantees

All sensitive credentials—including OAuth access/refresh tokens, custom endpoint API keys, and custom headers—are stored strictly in an encrypted vault.

### 4.1 Encryption Architecture
- **Storage File:** `provider_vault.enc` located in the application user data directory.
- **Cipher:** AES-256-GCM authenticated encryption.
- **Master Vault Key:** A 32-byte cryptographically random key generated on first initialization and stored directly in the operating system keyring:
  - **Windows:** Windows Credential Manager (`win32cred`).
  - **macOS:** macOS Keychain Services (`keychain`).
  - **Linux:** Freedesktop SecretService API / GNOME Keyring.
- **Zero Plaintext:** No API key or OAuth token is ever written to SQLite databases, unencrypted files, or client-accessible storage.

### 4.2 Keyring Availability & Recovery
When the operating system keyring is unavailable (e.g., locked session, headless Linux without D-Bus, or restricted Windows service account):
1. The vault enters `VaultState.UNAVAILABLE` and raises `VaultUnavailableError`.
2. The application degrades gracefully:
   - Existing direct providers configured via unencrypted `SystemConfig` (e.g. `direct:zen-free`) continue to function.
   - Proxy-based routes (`oauth:*`, `endpoint:*`) fail closed with HTTP 503 (`Vault is unavailable; unlock OS keyring`).
3. **Recovery Procedures:**
   - **Unlock OS Keyring:** Ensure user session is logged in and keyring daemon is unlocked.
   - **Provider-Scoped Vault Reset:** If the keyring key was permanently lost, users can call `POST /api/ai/routes/vault/reset`. This wipes only AI provider credentials in the vault without disturbing user trading layouts, preferences, or paper trading databases.

### 4.3 Secret Leakage Safeguards
- **Zero Secrets in URLs:** All credentials pass via headers or request bodies. No API key is ever accepted via query parameter.
- **Strict Log Redaction:** The backend logger, error handlers, and diagnostic endpoints pass all payloads through `redact_sensitive_data()`.
- **Ephemeral Sidecar Tokens:** `ProxySupervisor` generates fresh 32-character random tokens for `client_key` and `management_key` on each startup. These exist solely in memory and in 0600-permission temp files.

---

## 5. Proxy Lifecycle & Runtime Cleanup

The CLIProxyAPI process is strictly treated as an ephemeral local worker.

```
Application Start
       │
       ▼
[Find Free Loopback Port (127.0.0.1)]
       │
       ▼
[Create Ephemeral Dir (0700 permissions)]
       │
       ├──► Materialize OAuth & Custom Endpoint secrets (0600 permissions)
       │
       ├──► Write config.yaml (disable-control-panel, allow-remote: false)
       │
       ▼
[Spawn cliproxyapi.exe Sidecar]
       │
       ▼
[Healthz Polling (Readiness timeout 8s)] ───► Ready for Inference
       │
       │ (On Shutdown / Exit / Crash)
       ▼
[Stop Process (SIGTERM -> SIGKILL)]
       │
       ▼
[Wipe Ephemeral Directory & Files Recursively]
```

### 5.1 Runtime Isolation & Permissions
- **Loopback Only:** Configured with `host: "127.0.0.1"` and `allow-remote: false`. No external network interface is bound.
- **Control Panel Disabled:** `disable-control-panel: true` ensures no unauthenticated web UI is exposed.
- **File Permissions:** Runtime directory is restricted to `0700` (user-only read/write/execute); configuration and authentication files are set to `0600` (user-only read/write).

### 5.2 Clean Shutdown & Stale Directory Cleanup
- `ProxySupervisor.stop()` terminates the sidecar process and completely removes the ephemeral runtime directory.
- `atexit` and process signal handlers (`SIGTERM`, `SIGINT`) trigger synchronous cleanup during abnormal application termination.
- On initialization, `cleanup_stale_runtimes()` scans the runtime root for any orphaned directories from prior system crashes and wipes them before starting.

---

## 6. Legacy Model Migration

Upgrading from earlier BLM Terminal releases automatically migrates legacy model settings without user intervention.

### 6.1 Database & Token Migration (`legacy_migration.py`)
- **Execution:** Runs automatically during FastAPI application startup within the lifespan context manager (`backend/main.py` uses `lifespan` + `run_all_legacy_migrations`).
- **Codex Migration:** Extracts legacy access tokens and refresh tokens from `SystemConfig` and inserts them into `ProviderVault` under `oauth_auth/codex`.
- **Antigravity Migration:** Detects legacy token files on disk, verifies token validity, and migrates them into `ProviderVault`.
- **Model Migration:** Scans active chat sessions and system configuration. Maps unnamespaced legacy model strings (e.g. `gpt-4o`, `claude-3-5-sonnet`) to the qualified `blm:<active_route_id>/<upstream_model>` format using `map_legacy_model_to_route()`.
- **Transactional Safety:** Migrations run within atomic database transactions with automatic rollback on error.

---

## 7. Troubleshooting & Operational Guide

| Symptom | Probable Cause | Resolution |
|---|---|---|
| **HTTP 503: "Vault is unavailable"** | OS Keyring is locked or inaccessible | Log into desktop session; ensure GNOME Keyring / macOS Keychain is unlocked. In extreme cases, trigger `POST /api/ai/routes/vault/reset`. |
| **`ReadinessTimeoutError` on startup** | Port conflict or missing CLIProxyAPI binary | Production allocates an ephemeral loopback port; read the bound port from logs or `/api/ai/routes/diagnostics`; verify `vendor/cliproxyapi/runtime/cliproxyapi.exe` exists and has execute permissions. |
| **HTTP 401 / 429 on OAuth Route** | OAuth token expired or upstream rate limit | Open `AiProvidersModal`, click **Re-authenticate** for the affected account, or click **Reset Cooldown** if the limit has elapsed. |
| **Tool calls not executing** | Active route model does not support tool calling | Ensure active route is set to a model with function calling support (e.g. `gpt-4o`, `claude-3.5-sonnet`). |
| **Missing trace attribution in diagnostics** | Upstream or proxy omitted trace header | Verify proxy response includes `X-CPA-TRACE-ID`; check `GET /api/ai/routes/diagnostics` for recorded trace ring entries. |
