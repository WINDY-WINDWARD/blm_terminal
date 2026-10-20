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

