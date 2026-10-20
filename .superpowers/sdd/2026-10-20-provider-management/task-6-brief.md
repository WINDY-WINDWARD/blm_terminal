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

