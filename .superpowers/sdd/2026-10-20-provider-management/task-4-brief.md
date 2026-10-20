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

