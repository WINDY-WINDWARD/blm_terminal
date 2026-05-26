## Pull Request Description

---

### Summary

Remove Prisma (SQLite) dependency entirely and apply npm audit security patches.

---

### Why

**Prisma was redundant.** The application already persisted settings (`watchlistColumns`, `moversColumns`) via Jotai's `atomWithStorage` to sessionStorage. The `SettingsWidget` was making unnecessary round-trips to `/api/settings` to sync the same values to a SQLite database — a second persistence layer that provided no additional value over the existing client-side storage.

**Dead code.** The `TopMoverSymbol` model existed in the Prisma schema but was never used anywhere in the codebase.

**Security vulnerabilities.** The initial `npm audit` found 13 vulnerabilities (6 high, 7 moderate), including multiple in Prisma's dependency chain (e.g., `@hono/node-server`, `effect`, `defu`).

---

### What Changed

| Phase | Change |
|-------|--------|
| 1 | `SettingsWidget.tsx` — removed all `/api/settings` fetch calls, `scheduleSave` debounce, and `loading` state. Column changes now persist directly via `atomWithStorage` (sessionStorage). |
| 2 | Deleted `src/app/api/settings/route.ts` and `src/lib/prisma.ts` |
| 3 | Uninstalled `@prisma/adapter-better-sqlite3`, `@prisma/client`, `prisma`, `@prisma/dev` (63 packages removed) |
| 4 | Deleted `prisma/schema.prisma`, `prisma.config.ts`, `prisma/migrations/`, `prisma/dev.db` |
| 5 | Ran `npm audit fix` — patched 7 packages (hono, next, ws, fast-uri, defu, effect, brace-expansion) |

---

### Achieved

- **~830 lines deleted** across 4 commits
- **63 packages removed** from node_modules
- **Vulnerabilities: 13 → 2** (from 6 high + 7 moderate → 2 moderate)
- **All tests pass** (`npm test`: 114 passed)
- **Build succeeds**
- Settings continue to persist via existing `atomWithStorage` — no behavior change for users

---

### Remaining Vulnerabilities

2 moderate vulnerabilities remain in `postcss@8.4.31` bundled inside `next@16.2.6`. Fixing these requires next.js to update their bundled postcss, which is outside this PR's scope.
