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

