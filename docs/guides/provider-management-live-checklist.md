# Provider Management: Live Account & Tool Calling Verification Checklist

> **IMPORTANT: MANUAL TESTING ONLY — NON-CI**  
> This checklist requires live authenticated accounts and active upstream network connectivity.  
> **Do not run or automate this suite in CI environments.**

---

## 0. Prerequisites & Environment Setup

- [ ] **Desktop Application or Local Dev Server:**
  - Launch BLM Terminal desktop application, or run `npm run dev` with backend running on `http://127.0.0.1:8000`.
- [ ] **Account Credentials:**
  - A valid account for each OAuth provider/redirect pattern being tested: Codex, Antigravity, Claude, xAI, Kimi, Kimi AI, Meta, or Devin.
  - (Optional for custom endpoint testing) A live OpenAI-compatible endpoint (e.g. Ollama, LiteLLM, vLLM, or OpenRouter) with at least two API keys.
- [ ] **Clean Initial State:**
  - Ensure no orphaned `cliproxyapi.exe` processes exist in Task Manager / process monitor.
  - Verify OS Keyring is unlocked.

---

## 1. Scenario: OAuth Authentication & Account State

1. Open **AI Providers Modal** (via settings or Command Bar `Ctrl/Cmd + K` -> "AI Providers").
2. Repeat for each provider and each distinct redirect host/path pattern.
3. Click **Add Account**:
   - [ ] The system browser opens; no device-code option or device-flow request is shown.
   - [ ] For loopback mode, verify the redirect uses HTTP and a loopback host (`localhost`, `127.0.0.1`, or `::1`) and the callback listener is reachable only on that local host.
   - [ ] Authorize the application and confirm the exact provider callback path reaches the local success page.
   - [ ] For `callback_mode: "manual"`, paste the full redirect URL into the dialog and submit it; confirm the callback request is sent in its body and query values are absent from logs.
   - [ ] If the callback port is occupied, verify OAuth start reports `callback_port_unavailable` and does not bind a non-loopback interface.
4. **Verification:**
   - [ ] Success notification appears and account reconciliation completes.
   - [ ] Account is listed with email/account ID and an `Active` badge.
   - [ ] Route is marked as the `Active` route when selected.
   - [ ] Cancel or expire a pending session and verify its listener is released.

---

## 2. Scenario: Single Function / Tool Calling

1. Ensure the active route is set to the authenticated OAuth account (e.g. `blm:oauth:codex/gpt-4o`).
2. Open the **BLM Chat** widget.
3. Enter a prompt that deterministically triggers a single tool call:
   > *"What is the latest market price and day change for INFY (Infosys)?"*
4. **Verification:**
   - [ ] Assistant UI indicates tool execution in progress (e.g. `Executing: get_quote({"symbol": "INFY"})`).
   - [ ] Tool execution completes successfully without UI timeout.
   - [ ] Final assistant response displays the stock quote with market price, change, and analysis.
   - [ ] No raw JSON errors or uncaught exceptions in browser developer console.

---

## 3. Scenario: Parallel Tool Calls (`_run_tools_parallel`)

1. In the same chat session, enter a prompt requiring multiple simultaneous tool calls:
   > *"Compare the current price, 52-week range, and P/E ratio for TCS and RELIANCE."*
2. **Verification:**
   - [ ] Assistant issues parallel tool calls:
     - `get_quote({"symbol": "TCS"})`
     - `get_quote({"symbol": "RELIANCE"})`
   - [ ] Both tools execute concurrently via `_run_tools_parallel` (observe network/terminal logs).
   - [ ] Tool status badges update concurrently.
   - [ ] Assistant synthesizes both tool responses into a structured comparison table or bulleted summary.

---

## 4. Scenario: Session Continuity & Sticky Sessions

1. Submit a follow-up query relying on context from the previous turn:
   > *"Which of those two companies has higher trading volume today?"*
2. **Verification:**
   - [ ] Assistant answers accurately referring to TCS and RELIANCE without asking for clarification.
   - [ ] The request transmits the identical `X-Session-Id` header (observe via terminal logs or proxy trace).
   - [ ] The conversation sticks to the exact same OAuth account.

---

## 5. Scenario: Trace Attribution & Route Diagnostics

1. In BLM Terminal, navigate to **AI Diagnostics** or **Route Diagnostics** (or query `GET /api/ai/routes/diagnostics`).
2. **Verification:**
   - [ ] The recent requests are listed under Proxy Traces.
   - [ ] Each trace contains:
     - `trace_id`: Valid UUID / CPA trace format (from `X-CPA-TRACE-ID`).
     - `route_id`: Matches `oauth:codex`.
     - `upstream_model`: Matches `gpt-4o`.
     - `status_code`: 200.
     - `session_id`: Matches the chat session ID.
   - [ ] **Zero Secrets:** Confirm no access tokens, refresh tokens, or API keys appear in the diagnostic output.

---

## 6. Scenario: Custom Endpoint Multi-Key Failover (Optional)

1. In **AI Providers Modal**, create a new Custom Endpoint:
   - Base URL: Your live OpenAI-compatible endpoint URL.
   - Key 1: `sk-invalid-test-key-401` (Priority: 1, Weight: 1).
   - Key 2: Valid operational API key (Priority: 2, Weight: 1).
2. Activate the custom endpoint route and select an upstream model.
3. Send a chat completion request.
4. **Verification:**
   - [ ] Request completes successfully without an error dialog.
   - [ ] Key 1 received HTTP 401/429 and was placed into cooldown.
   - [ ] CLIProxyAPI failed over automatically to Key 2.
   - [ ] Response text streamed smoothly to the UI.

---

## 7. Scenario: Shutdown & Secret Hygiene Verification

1. Close the BLM Terminal application or terminate the dev server.
2. In PowerShell or Command Prompt, verify process cleanup:
   ```powershell
   Get-Process -Name "*cliproxy*" -ErrorAction SilentlyContinue
   ```
   - [ ] Output is empty (no orphaned `cliproxyapi` processes).
3. Check the temporary directory for runtime folders:
   ```powershell
   Get-ChildItem -Path $env:TEMP -Filter "*cliproxyapi*" -ErrorAction SilentlyContinue
   ```
   - [ ] Temporary runtime folder was deleted during shutdown.
4. Inspect `electron.log` and console logs:
   - [ ] Confirm no secrets, authorization tokens, or bearer headers were printed in plain text.

---

## 8. Scenario: Model Catalog & Cross-Route Worker Selection

1. With a migrated Antigravity account configured, open chat and both worker model selectors.
2. **Verification:**
   - [ ] `/api/ai/chat/models` returns model IDs without HTTP 500 when live model discovery times out.
   - [ ] Worker selectors group models by configured route and preserve route-qualified selections.
   - [ ] Select an enabled route different from the active chat route for Hunter or Verifier, then run the corresponding worker.
   - [ ] The worker trace shows the chosen route/model; interactive chat continues to use only the active route.
   - [ ] A saved model missing from its route catalog appears as unavailable and is not silently remapped.
