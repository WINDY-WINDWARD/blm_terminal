---
name: develop-ui
description: >
  UI development guide for the BLM Terminal project (Next.js 16 / React 19 / Tailwind v4 / Jotai).
  Use when: adding a new widget, editing an existing widget, making UI/styling changes, wiring
  state or data fetching, or running/testing the frontend. Covers design philosophy, theme tokens,
  the widget registration checklist, state management patterns, data fetching conventions, and
  dev/test commands.
---

# BLM Terminal – UI Developer Guide

## Design Philosophy

The UI replicates a Bloomberg/Reuters financial terminal aesthetic:

- **Black canvas, amber text** — dark background (`#000`), primary text `#ffb900` (amber).
- **Information density over whitespace** — pack as much data as possible into each panel; use `text-[9px]`–`text-xs` font sizes, tight leading, compact tables.
- **Monospace for data, sans-serif for chrome** — numbers and codes use `font-mono`; the command bar and labels use `font-sans`.
- **Color encodes meaning** — green (`#00ff00`) = positive/gain, red (`#ff0000`) = negative/loss, amber = neutral/primary, white = secondary/muted.
- **No decorative elements** — no drop shadows, no gradients, no rounded corners on data panels. Borders are `border-terminal-gray` (`#333`).
- **Panel-based layout** — the viewport is divided into resizable panels via `react-split`. Each panel holds exactly one widget, identified by an UPPER_CASE command name.

---

## Theme Tokens (Tailwind v4, `globals.css`)

| Token | Value | Usage |
|---|---|---|
| `bg-terminal-bg` | `#000000` | All panel backgrounds |
| `text-terminal-amber` | `#ffb900` | Primary text, labels, prices |
| `text-terminal-green` | `#00ff00` | Gains, positive changes |
| `text-terminal-red` | `#ff0000` | Losses, negative changes |
| `bg-terminal-gray` / `border-terminal-gray` | `#333333` | Dividers, panel headers, gutters |
| `font-mono` | JetBrains Mono / Consolas | All data, numbers, commands |
| `font-sans` | Inter | UI chrome (command bar) |

Custom Tailwind utilities defined in `globals.css`:
- `animate-ticker` – horizontal scrolling (LiveTicker)
- `animate-flash-green` / `animate-flash-red` – 400ms background flash on price tick changes

---

## Running & Testing

### Start development
```bash
# Terminal 1 – Next.js frontend (port 3000)
npm run dev

# Terminal 2 – Python FastAPI backend (port 4455)
cd backend
source .venv/bin/activate
uvicorn main:app --reload --port 4455
```

### Type-check & lint
```bash
npm run build   # TypeScript compile + Next.js build (catches all type errors)
npm run lint    # ESLint v9 flat config
```

### Python backend tests
```bash
cd backend
pytest                          # all tests
pytest -m "not slow"            # skip live NSE-hitting tests
```

No dedicated frontend test runner is configured; validate UI changes by running `npm run build` (zero type errors required) and visually inspecting in the browser.

---

## Adding a New Widget — Checklist

Every widget is an UPPER_CASE command string (e.g. `SCAN`, `ANNC`). Four files must be touched:

### 1. Create the widget component
`src/components/widgets/MyWidget.tsx`

```tsx
'use client';  // ← always first line

import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { useAtomValue } from 'jotai';
import { activeSymbolAtom } from '@/store/terminalStore';

export function MyWidget() {
  const symbol = useAtomValue(activeSymbolAtom);

  const { data, isLoading } = useQuery({
    queryKey: ['my-endpoint', symbol],
    queryFn: async () => {
      const res = await fetch(`/api/py/my-endpoint/${encodeURIComponent(symbol)}`);
      if (!res.ok) throw new Error('fetch failed');
      return res.json();
    },
    staleTime: 60_000,
  });

  if (isLoading) return <LoadingState />;

  return (
    <div className="h-full w-full flex flex-col font-mono text-xs overflow-auto bg-terminal-bg p-2">
      {/* content */}
    </div>
  );
}

function LoadingState() {
  return (
    <div className="h-full w-full flex items-center justify-center font-mono text-xs text-white/50">
      Loading...
    </div>
  );
}
```

Rules:
- Root element: `h-full w-full` so it fills the panel.
- Always provide a loading state (never a blank screen).
- Error state: `<div className="text-terminal-red/70 ...">` with message.
- Use `useAtomValue` for read-only atoms, `useAtom` for read-write.

### 2. Register in `Panel.tsx`
`src/components/Panel.tsx`

Add an import at the top:
```tsx
import { MyWidget } from './widgets/MyWidget';
```

Add a case to `renderWidget()`:
```tsx
case 'MYWIDGET': return <MyWidget />;
```

### 3. Register in `TerminalContainer.tsx`
`src/components/TerminalContainer.tsx`

Add the command string to `VALID_WIDGETS`:
```ts
const VALID_WIDGETS = [
  // ...existing entries...
  'MYWIDGET',
];
```

### 4. Register in `CommandBar.tsx`
`src/components/CommandBar.tsx`

Add an entry to `WIDGET_COMMANDS`:
```ts
{ cmd: 'MYWIDGET', desc: 'Short description shown in dropdown' },
```

---

## Editing an Existing Widget

Widgets live in `src/components/widgets/`. Each file exports a single named component matching the filename (PascalCase).

Common edit patterns:

| Task | Where |
|---|---|
| Add/remove a column in a table | Inside the widget TSX, update `thead` and `tbody` cells |
| Change data source / endpoint | Update `queryFn` in the `useQuery` call |
| Add persistent user config | Add a new `atomWithStorage` in `terminalStore.ts`, read it in the widget |
| Change refresh interval | Adjust `staleTime` / `refetchInterval` in `useQuery` |
| Add a sub-tab/view toggle | Use `useState<'tab1' \| 'tab2'>` locally inside the widget |
| Respond to global symbol change | Read `activeSymbolAtom` and include it in `queryKey` |

---

## State Management (Jotai)

All atoms live in `src/store/terminalStore.ts`. Never create atoms inside components.

```ts
// Read-only
const symbol = useAtomValue(activeSymbolAtom);

// Read-write
const [symbol, setSymbol] = useAtom(activeSymbolAtom);

// Persist to localStorage
export const myAtom = atomWithStorage<string>('terminal.myKey', 'default');
```

Key shared atoms:
- `activeSymbolAtom` – currently selected trading symbol (e.g. `'RELIANCE'`)
- `activeExchangeAtom` – exchange (`'NSE'`, `'BSE'`, etc.)
- `tickDataAtom` – live WebSocket tick data keyed by `'SYMBOL.EXCHANGE'`
- `focusedPanelAtom` – which panel is currently focused
- `activePanelsAtom` – maps panel ID → widget command name

---

## Data Fetching Conventions

- **Always use `useQuery`** (or `useMutation`) from `@tanstack/react-query`. Never `useEffect + fetch + useState`.
- **Python backend**: call `/api/py/<endpoint>` — the Next.js catch-all proxy at `src/app/api/py/[...path]/route.ts` forwards to FastAPI at `PYTHON_BACKEND_URL` (default `http://localhost:4455`).
- **OpenAlgo broker API**: use `OpenAlgoClient` from `@/lib/openalgo` or call `/api/openalgo/<endpoint>`.
- **Include symbol in queryKey** so React Query re-fetches when the active symbol changes:
  ```ts
  queryKey: ['endpoint-name', symbol]
  ```
- Check `data?.error` for proxy error responses — they return `{ error: string }` with HTTP 4xx/5xx.

---

## Widget Layout Patterns

See `references/widget-patterns.md` for reusable JSX snippets: loading/error states, header bars, scrollable tables, tab bars, and color-coded cells.

---

## File Map (Quick Reference)

| File | Purpose |
|---|---|
| `src/app/globals.css` | Theme tokens (colors, fonts, keyframes) |
| `src/store/terminalStore.ts` | All Jotai atoms |
| `src/components/Panel.tsx` | Widget router — maps command → component |
| `src/components/TerminalContainer.tsx` | `VALID_WIDGETS` list + keyboard shortcuts |
| `src/components/CommandBar.tsx` | `WIDGET_COMMANDS` list shown in dropdown |
| `src/components/GridSystem.tsx` | Resizable panel grid (react-split) |
| `src/components/widgets/` | All widget components (one file each) |
| `src/lib/socket.ts` | `wsService` singleton for WebSocket ticks |
| `src/app/api/py/[...path]/route.ts` | Proxy to Python FastAPI backend |
