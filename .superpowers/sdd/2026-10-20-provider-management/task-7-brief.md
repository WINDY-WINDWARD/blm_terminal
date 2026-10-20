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

