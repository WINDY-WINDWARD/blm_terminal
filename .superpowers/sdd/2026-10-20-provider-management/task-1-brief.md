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

