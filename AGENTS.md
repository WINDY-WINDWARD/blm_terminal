# AGENTS.md

Guidelines for AI coding agents working in this repository.

---

## Project Overview

A financial terminal UI built with **Next.js 16 (App Router)**, **React 19**, **TypeScript**, **Tailwind CSS v4**, **Jotai** for state, and **Socket.IO** for real-time data. The UI renders resizable panels, each hosting a widget (chart, order entry, positions, watchlist, top movers) that connect to the OpenAlgo trading API.

---

## Tech Stack

| Layer | Library/Tool |
|---|---|
| Framework | Next.js 16.1.6 (App Router) |
| UI | React 19, Tailwind CSS v4 |
| State | Jotai v2 (atomic) |
| Data fetching | @tanstack/react-query v5 (installed, not yet wired up) |
| Charts | lightweight-charts v5 (TradingView) |
| Icons | lucide-react (installed, not yet used) |
| WebSocket | socket.io-client v4 |
| REST client | Custom `OpenAlgoClient` in `src/lib/openalgo.ts` |
| Class utilities | clsx + tailwind-merge (installed, not yet used) |
| Package manager | npm |

---

## Commands

### Development

```bash
npm run dev       # Start Next.js dev server with hot reload
npm run build     # Production build
npm start         # Serve the production build
npm run lint      # Run ESLint (ESLint v9 flat config)
```

### Tests

No test framework is configured yet. When tests are added, place them in
`src/__tests__/` or co-locate as `*.test.tsx` / `*.spec.tsx` next to the
source file they test.

When a test runner (Jest or Vitest recommended) is added, a single test can
typically be run with:

```bash
# Vitest (recommended for Next.js + Vite ecosystem)
npx vitest run src/components/CommandBar.test.tsx

# Jest
npx jest src/components/CommandBar.test.tsx
```

---

## Directory Structure

```
src/
├── app/              # Next.js routing layer
│   ├── api/          # API routes (backend)
│   │   ├── openalgo/ # OpenAlgo proxy routes (added)
│   │   │   ├── positions/route.ts   # GET /api/openalgo/positions
│   │   │   ├── orders/route.ts      # GET /api/openalgo/orders
│   │   │   ├── trades/route.ts      # GET /api/openalgo/trades
│   │   │   ├── funds/route.ts       # GET /api/openalgo/funds
│   │   │   ├── quotes/route.ts      # POST /api/openalgo/quotes
│   │   │   ├── history/route.ts     # POST /api/openalgo/history
│   │   │   └── placeorder/route.ts  # POST /api/openalgo/placeorder
│   │   ├── top-symbols/route.ts     # Existing
│   │   └── watchlist/route.ts       # Existing
│   ├── globals.css   # Tailwind v4 @theme tokens + global resets
│   ├── layout.tsx    # Root layout (fonts, <body>)
│   └── page.tsx      # Entry page — renders <TerminalContainer>
├── components/       # Reusable React UI components
│   ├── widgets/      # One file per widget type
│   │   ├── ChartWidget.tsx
│   │   ├── OrderWidget.tsx
│   │   ├── PosWidget.tsx
│   │   ├── TopWidget.tsx
│   │   └── WatchWidget.tsx
│   ├── CommandBar.tsx
│   ├── GridSystem.tsx
│   ├── LiveTicker.tsx
│   ├── Panel.tsx
│   └── TerminalContainer.tsx
├── lib/              # Pure utility/service singletons
│   ├── openalgo.ts              # Client REST API client (calls Next.js proxy)
│   ├── openalgo-server.ts       # Server-side REST client (calls OpenAlgo directly)
│   ├── socket.ts                # Socket.IO singleton
│   ├── logger.ts                # Structured logging utility (added)
│   ├── cache.ts                 # In-memory cache with TTL support (added)
│   ├── rate-limiter.ts          # Rate limiting utility (added)
│   └── api-config.ts            # Centralized API configuration (added)
└── store/
    └── terminalStore.ts  # All Jotai atoms (global state)
```

---

## Code Style

### TypeScript

- **Strict mode is enabled** (`"strict": true` in `tsconfig.json`). All new code must pass strict type checks.
- Target: `ES2017`. Module resolution: `bundler`. `noEmit: true` (Next.js handles compilation).
- Prefer explicit types over `any`. The existing `catch (err: any)` and `as any` casts are technical debt — use `unknown` + type narrowing for new error handlers.
- Use `unknown` in `catch` blocks and narrow with `instanceof Error` checks:
  ```ts
  catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Unknown error';
  }
  ```
- Generic functions and classes are preferred over overloaded signatures — see `OpenAlgoClient.request<T>()`.

### Imports

- Use the `@/` path alias (maps to `src/`) for all cross-directory imports:
  ```ts
  import { activeCommandAtom } from '@/store/terminalStore';
  import { OpenAlgoClient } from '@/lib/openalgo';
  ```
- Use relative imports only for same-directory imports:
  ```ts
  import { Panel } from './Panel';
  import { TopWidget } from './widgets/TopWidget';
  ```
- Preferred import order (not enforced by a plugin — follow manually):
  1. `react` and `next/*`
  2. Third-party libraries
  3. Internal `@/` alias imports
  4. Relative `./` imports

### React Components

- All interactive client-side components must have `'use client';` as the very first line.
- One component per file. File name must match the exported component name (PascalCase).
- Use function declarations for top-level page/layout components; arrow functions are fine for small helpers and callbacks within a component.
- Props interfaces are declared inline or as `interface ComponentNameProps` directly above the component.

### Naming Conventions

| Entity | Convention | Example |
|---|---|---|
| React components | PascalCase | `TerminalContainer`, `ChartWidget` |
| Component files | PascalCase | `CommandBar.tsx`, `PosWidget.tsx` |
| Non-component functions | camelCase | `handleKeyDown`, `handleOrder` |
| Variables / state | camelCase | `inputVal`, `focusedPanel` |
| Jotai atoms | camelCase + `Atom` suffix | `activeCommandAtom`, `activePanelsAtom` |
| TypeScript interfaces | PascalCase | `PanelProps`, `OrderParams` |
| Classes | PascalCase | `OpenAlgoClient`, `WebSocketService` |
| Exported singletons | camelCase | `wsService` |
| CSS custom properties | kebab-case with prefix | `--color-terminal-bg`, `--font-mono` |
| Tailwind design tokens | kebab-case | `terminal-bg`, `terminal-amber` |
| Widget command strings | UPPER_CASE | `'TOP'`, `'POS'`, `'ORDER'`, `'CHART'` |

### CSS and Tailwind

- Use **Tailwind CSS v4 utility classes** for all styling. Avoid inline `style={{}}` props except for dynamic values that cannot be expressed as utilities (e.g., calculated widths from state).
- Design tokens (colors, fonts) are defined in `src/app/globals.css` under `@theme`. Add new tokens there — do not hardcode hex values in component files.
- Use `clsx` + `tailwind-merge` (both installed) for conditional or merged class strings:
  ```ts
  import { clsx } from 'clsx';
  import { twMerge } from 'tailwind-merge';
  const cn = (...inputs: ClassValue[]) => twMerge(clsx(inputs));
  ```
- The terminal aesthetic uses amber (`terminal-amber`), green (`terminal-green`), red (`terminal-red`), and a dark background (`terminal-bg`). Maintain this palette.

### State Management (Jotai)

- All global state lives in `src/store/terminalStore.ts`. Add new atoms there.
- Atoms are typed generically: `atom<string>('')`, `atom<Record<string, string>>({})`.
- Prefer primitive atoms + derived `atom(get => ...)` for computed values. Avoid putting complex objects in a single large atom.

### Error Handling

- **API errors**: The proxy routes catch errors from `OpenAlgoServerClient` and return formatted error responses. Catch at the call site in components and display user-facing messages.
- **Network errors**: The `OpenAlgoServerClient` distinguishes between connection failures, timeouts, and API errors. Check server logs for details.
- **Socket errors**: Register an `'error'` handler on the Socket.IO client when adding new socket logic.
- **Guard against null refs**: Before DOM operations, check: `if (!ref.current) return;`
- **No global ErrorBoundary yet**: Add one at the `<TerminalContainer>` level if widgets start making real API calls.

### Async / Data Fetching

- `@tanstack/react-query` is installed for server-state management — use it for all data fetching in new widgets rather than raw `useEffect` + `useState` for async data.
- WebSocket subscriptions go through the `wsService` singleton in `src/lib/socket.ts`.

---

## Environment Variables

### Server-Only Variables (Never exposed to browser)

These variables are only used on the backend and are **never** sent to the client:

```
OPENALGO_URL=http://localhost:8800           # OpenAlgo API base URL
OPENALGO_API_KEY=<your_api_key>              # OpenAlgo API key
OPENALGO_TIMEOUT_MS=10000                    # API request timeout (milliseconds)
RATE_LIMIT_PER_MINUTE=60                     # Global rate limit (requests/minute)
```

### Client-Side Variables (Exposed to browser)

These variables are prefixed with `NEXT_PUBLIC_` and are safe to expose to the browser:

```
NEXT_PUBLIC_OPENALGO_WS_URL=ws://localhost:8765     # WebSocket URL for real-time data
NEXT_PUBLIC_OPENALGO_DEFAULT_EXCHANGE=NSE           # Default exchange (NSE, BSE, etc.)
```

### API Proxy Architecture

The application uses a **Next.js API proxy layer** to communicate with the OpenAlgo API:

```
Browser (localhost:3000)
  ↓
Next.js API Routes (/api/openalgo/*)  ← Same-origin, no CORS issues
  ↓ (Server-side)
OpenAlgo API (localhost:8800)          ← API key stays on server
```

**Benefits:**
- ✅ **Zero CORS errors** - all browser requests are same-origin
- ✅ **Improved security** - API key never exposed to browser
- ✅ **Caching** - reduces redundant API calls (configurable per endpoint)
- ✅ **Rate limiting** - protects against API abuse and prevents rate limit hits
- ✅ **Request logging** - structured logging for debugging
- ✅ **Timeout configuration** - prevents hanging requests
- ✅ **Type safety** - TypeScript interfaces maintained throughout the stack

### Cache Configuration

Each endpoint has a configurable Time-To-Live (TTL) in `src/lib/api-config.ts`:

| Endpoint | TTL | Reason |
|---|---|---|
| positions | 2s | Near real-time position updates |
| orders | 2s | Near real-time order status |
| trades | 2s | Near real-time trade data |
| funds | 5s | Account balance updates |
| quotes | 1s | Real-time market data (shortest TTL) |
| history | 5min | Historical data (longest TTL) |
| placeorder | 0s | No caching (mutating endpoint) |

### Rate Limiting

Rate limits are enforced per endpoint to prevent API abuse:

| Endpoint | Limit |
|---|---|
| All read endpoints | 60 req/min |
| placeorder | 30 req/min (stricter for safety) |

Exceeding rate limits returns HTTP 429 (Too Many Requests).

---

## No Cursor or Copilot Rules

No `.cursorrules`, `.cursor/rules/`, or `.github/copilot-instructions.md` files exist in this repository.
