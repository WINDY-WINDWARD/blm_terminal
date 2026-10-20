# Task 1 Report: Vault, route registry, and persistence foundation

## Summary
Task 1 establishes the persistent, encrypted foundation for the CLIProxyAPI multi-provider management architecture in BLM Terminal. It introduces the OS-keyring-backed AES-256-GCM vault, route/credential database models and Alembic migration, idempotent route seeding, and central route and model qualification helpers.

## Deliverables Completed

1. **Dependencies (`backend/pyproject.toml`)**:
   - Added `keyring>=24.0.0` and `psutil>=6.0.0` to project dependencies.
   - Installed packages into backend virtual environment.

2. **PyInstaller Build Scripts (`scripts/build_backend.ps1`, `scripts/build_backend.sh`)**:
   - Added `--collect-all "keyring"` to bundle keyring metadata, entry points, and subpackages.
   - Added `--hidden-import "keyring.backends.Windows"` and `--hidden-import "keyring.backends.macOS"` to ensure platform keyring backends freeze cleanly across Windows and macOS targets.

3. **Database Models (`backend/app/models/ai_provider.py`)**:
   - `AIProviderRoute`:
     - Columns: `id` (primary key), `kind`, `provider`, `display_label`, `proxy_prefix` (unique index), `enabled`, `config_json`, `created_at`, `updated_at`.
     - Relationship: `credentials` with `lazy="selectin"` and cascade delete.
   - `AIProviderCredential`:
     - Columns: `id` (primary key), `route_id` (foreign key), `kind`, `vault_reference`, `proxy_credential_name`, `masked_identity`, `priority`, `weight`, `enabled`, `status`, `cooldown`, `last_redacted_error`, `created_at`, `updated_at`.
     - Relationship: `route` with `lazy="selectin"`.
     - Ergonomic properties: `vault_ref`, `masked_label`, `last_error`, `cooldown_until`.
   - Registered `ai_provider` in `backend/app/models/__init__.py`.

4. **Alembic Migration (`backend/alembic/versions/k11111111111_add_ai_provider_routes_and_credentials.py`)**:
   - Revision `k11111111111`, down revision `j88888888888`.
   - Idempotent table and index creation for `ai_provider_routes` and `ai_provider_credentials`.
   - Seeds the 8 OAuth routes (`codex`, `antigravity`, `claude`, `xai`, `kimi`, `kimi-ai`, `meta`, `devin`) with deterministic prefixes `blm-<first 16 hex of sha256(route_id)>`.
   - Reversible downgrade drops credentials and routes tables.
   - Updated `backend/alembic/env.py` to import `ai_provider` model.

5. **Lifespan Startup Hook (`backend/main.py`)**:
   - Added `_ensure_ai_provider_routes()` to ensure OAuth routes are present even in offline/create_all fallback bootstrap paths.

6. **Versioned Vault Service (`backend/app/services/provider_vault.py`)**:
   - AES-256-GCM authenticated encryption using `cryptography`.
   - 32-byte encryption key managed via Python `keyring` under service `blm-terminal-provider-vault`, account `v1`.
   - Restrictive file permissions (0600) and atomic file replacement via temporary write and `os.replace`.
   - In-process `asyncio.Lock` serialization.
   - Dedicated accessors for OAuth auth JSON, endpoint headers, endpoint keys, and cooldown status snapshots (`.cds`).
   - Generic `vault_reference` accessors (`get_secret`, `set_secret`, `delete_secret`).
   - Explicit states: `VaultState.AVAILABLE`, `VaultState.KEYRING_UNAVAILABLE`, `VaultState.VAULT_CORRUPT`.
   - Zero secret logging: values, headers, and token bodies are never logged.

7. **Route and Model Helpers (`backend/app/services/route_registry.py`, `backend/app/services/provider_registry.py`)**:
   - `resolve_active_route_id`: Resolves active route from `system_config` key `ai.provider` or settings defaults.
   - `normalize_legacy_provider_id`: Normalizes legacy IDs (`gemini` -> `antigravity`, `zen`/`zen-free` -> `zen-paid`).
   - `provider_to_route_id`: Maps legacy provider or route string to canonical route ID (`oauth:...`, `direct:...`, `endpoint:...`).
   - `format_route_model_id` / `parse_route_model_id`: Formats and parses `blm:<route_id>/<upstream_model>`, splitting at the first slash after `blm:` to correctly preserve slash-containing model names.
   - `map_legacy_model_to_route`: Remaps bare legacy model strings or stale cross-route models to the target route.
   - `validate_model_for_route` / `ensure_model_belongs_to_route`: Enforces that models belong to the active route and allowed catalog.
   - `seed_oauth_routes` / `seed_oauth_routes_sync`: Idempotent seeding helpers.

## Verification
- `pytest tests/test_provider_vault_and_registry.py`: 20 passed.
- `pytest tests/test_multi_provider_offline.py`: 10 passed.
- `pytest tests/test_security_guards.py`: 4 passed.
- `pytest tests/test_main_wiring.py`: 5 passed.
- Combined suite: 34 passed, 0 failures.
- Direct migration verification: `upgrade` -> seeded 8 routes verified -> `downgrade` verified.

## Concerns
None. The persistent foundation and cryptographic interfaces are self-contained and align with all downstream specifications for Tasks 2-8.
