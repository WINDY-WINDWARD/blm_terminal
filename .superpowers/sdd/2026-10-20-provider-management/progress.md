# SDD ledger — plan: docs/superpowers/plans/2026-10-20-provider-management.md

## Setup
- Worktree: C:\projects\blm_projects\blm_terminal\.worktrees\provider-management
- Branch: feat/provider-management
- Base: 4fe6573a (origin/main)
- Baseline: backend/test_multi_provider_offline.py + test_security_guards.py: 14 passed
- Spec note: approved plan in docs/superpowers/plans/2026-10-20-provider-management.md is the available binding specification.

## Pre-flight cross-task scan
| Task pair | Producer -> consumer | Result |
|---|---|---|
| T1 -> T2 | vault/route registry -> supervisor materialization | clean |
| T1 -> T3 | route helpers -> inference/model catalog | clean |
| T1 -> T4 | DB tables/vault -> provider APIs | clean |
| T2 -> T3 | supervisor client -> proxy-backed inference | clean |
| T2 -> T4 | management client -> OAuth/account APIs | clean |
| T3 -> T5 | provider redaction surface -> system-config secrets | overlap: resolve in T5, no contradictory requirement |
| T4 -> T6 | provider APIs -> modal | clean |
| T3/T5 -> T7 | model/API contracts -> selectors | clean |
| T6 -> T7 | shared modal -> endpoint/direct tabs | clean |
| T8 | depends on all prior interfaces | intentionally final |

## Tasks
- [x] Task 1: Vault, route registry, and persistence foundation
- [ ] Task 2: CLIProxyAPI packaging, supervisor, and lifecycle
- [ ] Task 3: Route-aware inference, model catalog, and legacy migration
- [ ] Task 4: Provider management API
- [ ] Task 5: Security redaction and server-only OpenAlgo credentials
- [ ] Task 6: Unified provider modal and OAuth account management UI
- [ ] Task 7: Custom endpoints, direct providers, and model-selector integration
- [ ] Task 8: Documentation, release assets, and end-to-end verification

- Task 1 baseline: 9a115897

- Baseline frontend: npm test -- --run => 3 environment-dependent files failed (marketWs/DealsWidget/PosWidget; port 3000 ECONNREFUSED), 50 files and 465 tests passed.
