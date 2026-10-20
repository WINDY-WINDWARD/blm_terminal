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

