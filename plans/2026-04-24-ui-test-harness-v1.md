# UI Test Harness

## Objective

Establish a complete test harness for the `blm_terminal` Next.js/React 19 frontend. Currently zero test infrastructure exists. The goal is to introduce Vitest + React Testing Library, define mock boundaries for all external dependencies (WebSocket, REST APIs, localStorage, `lightweight-charts`, `react-split`), and produce a full suite of unit, component, and behavioural tests covering all 15 widgets plus every shared infrastructure component and pure utility function.

---

## Codebase Assessment

| Layer | Files | Testable Surface |
|---|---|---|
| Store / atoms | `src/store/terminalStore.ts` | `createDefaultPanelSizes`, atom shapes, default values |
| Lib utilities | `src/lib/utils.ts`, `src/lib/openalgo.ts`, `src/lib/socket.ts` | `cn()`, `OpenAlgoClient` methods, `WebSocketService` state machine |
| Infrastructure components | `ErrorBoundary`, `Panel`, `CommandBar`, `TerminalContainer`, `GridSystem`, `LiveTicker`, `Providers` | Focus, routing, keyboard handling, WS lifecycle |
| Widget components | 15 widgets (ChartWidget through ScanWidget) | Rendering states, user interactions, query-driven UI |
| Pure functions (inline) | `ChartWidget`, `WatchWidget`, `MoversWidget`, `NotifWidget`, `LiveTicker` | Date helpers, candle math, formatting, sort comparators |

---

## Risks Identified

1. **Jotai `atomWithStorage` uses `localStorage`** — must be cleared/reset between tests; requires a custom Jotai `Provider` wrapper with fresh store per test.
2. **`wsService` is a singleton** — state bleeds between tests unless the instance is reset or fully mocked before each test.
3. **`lightweight-charts` `createChart` touches the real DOM canvas API** — will throw in jsdom; must be mocked at the module level.
4. **`react-split` uses `getBoundingClientRect`** — must be mocked as a pass-through wrapper.
5. **TanStack Query cache persists** — every test needs a fresh `QueryClient` to avoid stale data bleed.
6. **`ReactDOM.createPortal`** in `NotifWidget` — requires `document.body` to exist in jsdom (it does) but the portal target must be in the query scope.
7. **`next/navigation`** hooks used indirectly — no direct usage found, but `Providers` / layout wrappers should stub it.

---

## Implementation Plan

### Phase 1 — Test Framework & Tooling Setup

- [x] Task 1.1. **Install Vitest as the test runner** along with `@vitest/ui`, `@vitest/coverage-v8`, and `vite` (as peer). Vitest is preferred over Jest here because it has native ESM support (needed for `lightweight-charts` v5, `jotai` v2, and `@tanstack/react-query` v5 — all published as ESM-first packages), avoids `babel-jest` transform complexity, and runs faster in watch mode.

- [x] Task 1.2. **Install `@testing-library/react` (v16+, compatible with React 19), `@testing-library/user-event` v14, and `@testing-library/jest-dom`** for component assertion matchers. Add `@vitest/dom` or import `@testing-library/jest-dom/vitest` in the setup file to extend `expect`.

- [x] Task 1.3. **Install `msw` (Mock Service Worker) v2** for HTTP request interception. MSW v2 uses the `http` handler API and works in Node via `@mswjs/interceptors` without a service worker, making it suitable for both jsdom unit tests and (later) browser integration tests.

- [x] Task 1.4. **Install `happy-dom`** as the jsdom alternative environment (specified per-file or globally) — it is faster and handles `ResizeObserver`, `localStorage`, and `getComputedStyle` better than jsdom for this React 19 + Tailwind stack.

- [x] Task 1.5. **Create `vitest.config.ts`** at the repo root (not inside `src/`). Configure:
  - `environment: 'happy-dom'`
  - `globals: true` (so `describe`, `it`, `expect`, `vi` are available without imports)
  - `setupFiles: ['src/__tests__/setup.ts']`
  - `resolve.alias` mirroring the `@/` alias from `tsconfig.json`
  - `coverage.provider: 'v8'` targeting `src/**/*.{ts,tsx}` excluding `app/api/**` (API routes are server-side and tested via Python backend tests)
  - `testMatch` patterns for `src/**/*.{test,spec}.{ts,tsx}`

- [x] Task 1.6. **Create `src/__tests__/setup.ts`** — the global test setup file. It must:
  - Import and call `@testing-library/jest-dom/vitest` to attach all DOM matchers
  - Start the MSW server with `server.listen({ onUnhandledRequest: 'warn' })`
  - Reset MSW handlers after each test with `server.resetHandlers()`
  - Close MSW server after all tests with `server.close()`
  - Call `localStorage.clear()` in `afterEach` to prevent `atomWithStorage` bleed

- [x] Task 1.7. **Add `"test"` and `"test:ui"` scripts** to `package.json`:
  - `"test": "vitest run"`
  - `"test:watch": "vitest"`
  - `"test:ui": "vitest --ui"`
  - `"test:coverage": "vitest run --coverage"`

---

### Phase 2 — Global Mock Modules

- [x] Task 2.1. **Create `src/__tests__/mocks/wsService.ts`** — a full mock of `src/lib/socket.ts`. The mock must expose the same public surface (`connect`, `disconnect`, `subscribe`, `unsubscribe`, `onTick`, `onConnectionChange`, `isConnected`) with `vi.fn()` stubs. `onTick` and `onConnectionChange` should return an unsubscribe function that is itself a `vi.fn()`. This mock is registered via `vi.mock('@/lib/socket')` in each test file that touches WebSocket-connected components. The module must also expose a `__triggerTick(data: TickData)` and `__triggerConnection(state: boolean)` test-only helper so tests can fire events into components synchronously.

- [x] Task 2.2. **Create `src/__tests__/mocks/lightweightCharts.ts`** — a mock for `lightweight-charts`. The mock must export a `createChart` that returns a stub object with methods: `addSeries`, `remove`, `applyOptions`, `timeScale` (returns `{ fitContent: vi.fn(), setVisibleRange: vi.fn() }`), `subscribeCrosshairMove`, `unsubscribeCrosshairMove`. The `addSeries` must return a stub with `setData`, `update`, `priceScale`. Register with `vi.mock('lightweight-charts', ...)` in `vitest.config.ts` using the `__mocks__` convention or inline `vi.mock()` at the top of `ChartWidget` test files.

- [x] Task 2.3. **Create `src/__tests__/mocks/reactSplit.tsx`** — mock for `react-split`. Render children as a `<div style={{ display: 'flex' }}>` pass-through and expose a `onDragEnd` spy so tests can simulate resize events.

- [x] Task 2.4. **Create `src/__tests__/mocks/msw-handlers.ts`** — central MSW request handler registry. Define handlers for every API endpoint consumed by the UI:
  - `GET /api/py/market/top-gainers` → returns fixture `gainers[]`
  - `GET /api/py/market/top-losers` → returns fixture `losers[]`
  - `GET /api/py/market/symbol-data/:symbol` → returns fixture `NseSymbolData`
  - `GET /api/py/market/change-ranges/:symbol` → returns fixture `ChangeRanges`
  - `GET /api/py/morningstar/fairvalue/:symbol` → returns fixture `{ fairValue: 1234 }`
  - `GET /api/py/notifications` → returns fixture `Notification[]`
  - `DELETE /api/py/notifications/:id` → returns `204`
  - `DELETE /api/py/notifications` → returns `204`
  - `GET /api/watchlist` → returns fixture `WatchlistItem[]`
  - `POST /api/watchlist` → returns new `WatchlistItem`
  - `DELETE /api/watchlist` → returns `200`
  - `GET /api/watchlists` → returns fixture `Watchlist[]`
  - `POST /api/watchlists` → returns new `Watchlist`
  - `GET /api/event-calendar` → returns `[]`
  - `GET /api/event-calendar/past` → returns `[]`
  - `POST /api/openalgo/funds` → returns fixture `FundsData`
  - `POST /api/openalgo/orders` → returns fixture `OrderBook`
  - `POST /api/openalgo/positions` → returns fixture `PositionBook`
  - `POST /api/openalgo/placeorder` → returns `{ status: 'success', orderid: 'TEST001', message: 'Order placed' }`
  - `POST /api/openalgo/history` → returns fixture `HistoricalBar[]`
  - `GET /api/openalgo/ws-token` → returns `{ api_key: 'TEST_KEY' }`
  - `GET /api/py/stockuniverse/search/:query` → returns fixture `AutocompleteResult[]`
  - `GET /api/settings` → returns fixture `UserSettings`

- [x] Task 2.5. **Create `src/__tests__/fixtures/` directory** with typed fixture files:
  - `market.ts` — `gainers`, `losers`, `symbolData`, `changeRanges`, `historicalBars`
  - `watchlist.ts` — `watchlists`, `watchlistItems`
  - `trading.ts` — `orderBook`, `positionBook`, `fundsData`
  - `notifications.ts` — `notifications` array covering all `trigger_type` variants

- [x] Task 2.6. **Create `src/__tests__/utils/renderWithProviders.tsx`** — a custom render wrapper that wraps every component under test with:
  - Fresh `QueryClient` (with `retry: false`, `gcTime: 0` to prevent async bleed)
  - `QueryClientProvider`
  - Jotai `Provider` with a fresh `createStore()` per test (prevents `atomWithStorage` bleed)
  - Any other context providers needed  
  This utility should accept `initialAtomValues?: [WritableAtom, unknown][]` so tests can seed Jotai state.

---

### Phase 3 — Pure Utility Function Tests

- [ ] Task 3.1. **`src/__tests__/store/terminalStore.test.ts`** — test `createDefaultPanelSizes`:
  - For each `PanelCount` (2, 4, 6, 8): verify `rowSizes` length equals `PANEL_LAYOUTS[n].rows`, each `colSizes` row has length equal to `PANEL_LAYOUTS[n].cols`, all percentages sum to 100 within each row and overall.
  - Verify `DEFAULT_ACTIVE_PANELS` has exactly 8 keys with correct widget names.
  - Verify atom default values are exported as expected types.

- [ ] Task 3.2. **`src/__tests__/lib/utils.test.ts`** — test `cn()`:
  - Merges conflicting Tailwind classes (e.g., `cn('p-2', 'p-4')` → `'p-4'`).
  - Handles falsy values (`cn('a', false, undefined, 'b')` → `'a b'`).
  - Handles conditional objects (`cn({ 'text-red': true, 'text-green': false })` → `'text-red'`).

- [ ] Task 3.3. **`src/__tests__/widgets/chartWidget.utils.test.ts`** — extract and test the four pure helpers currently inlined in `ChartWidget.tsx`:
  - `formatDate(date)`: returns `YYYY-MM-DD` in IST timezone regardless of UTC offset; verify with a fixed date.
  - `getDateRange(interval)`: for `'1m'` the start is 5 days before end; for `'D'` start is 1 year before; end is always today's IST date.
  - `getCandlePeriodSeconds(interval)`: verify all five mappings (`1m`→60, `5m`→300, `15m`→900, `1h`→3600, `D`→86400).
  - `alignToCandle(timestampSeconds, periodSeconds)`: `alignToCandle(305, 300)` → `300`; `alignToCandle(600, 300)` → `600`; `alignToCandle(0, 60)` → `0`; verify always returns a multiple of `periodSeconds`.

- [ ] Task 3.4. **`src/__tests__/widgets/watchWidget.utils.test.ts`** — test the pure helpers currently inlined in `WatchWidget.tsx`:
  - `compareValues(a, b, direction)`: null sorts last regardless of direction; ascending numeric order; descending string order; mixed null/non-null; equal values return 0.
  - `formatResultsDate('12-Apr-2025')` → `'12 Apr'`; invalid string passes through unchanged.
  - `formatRange(null)` renders a dash; positive values render green with `+`; negative values render red without `+`.
  - `formatPrice(null)` renders a dash; numeric values render `.toFixed(2)`.

- [ ] Task 3.5. **`src/__tests__/widgets/moversWidget.utils.test.ts`** — test `formatChange` and `formatRange` from `MoversWidget.tsx`:
  - `formatChange(5.5)` produces a green `+5.50%` span.
  - `formatChange(-2.1)` produces a red `-2.10%` span.
  - `formatChange(null)` renders a dash.
  - `formatPriceCell(1234.5)` → `'1234.50'`; `formatPriceCell(null)` → dash.

- [ ] Task 3.6. **`src/__tests__/widgets/notifWidget.utils.test.ts`** — test pure helpers from `NotifWidget.tsx`:
  - `getBadgeColor`: verify each of the 27 trigger types returns a non-empty Tailwind class string; verify default fallback.
  - `getBadgeLabel`: verify all 27 mappings return correct short labels; verify unknown type returns `triggerType.toUpperCase()`.
  - `getTooltipDescription`: verify the 27 defined cases return non-empty descriptions; unknown type returns the type itself.
  - `formatTime('2025-04-24T09:15:00.000Z')`: returns `HH:MM` in local time; verify padded output for single-digit values.

- [ ] Task 3.7. **`src/__tests__/components/liveTicker.utils.test.ts`** — test `toNum` and `normalise` from `LiveTicker.tsx`:
  - `toNum(2450.3)` → `2450.3`; `toNum('2,450.30')` → `2450.3`; `toNum(null)` → `0`; `toNum('')` → `0`.
  - `normalise([{ symbol: 'RELIANCE', lastPrice: '2,450.30', change: '10', pChange: '0.4', previousClose: '2440' }])` returns a typed `NseEquity` array with all fields as numbers.

---

### Phase 4 — Infrastructure Component Tests

- [ ] Task 4.1. **`src/__tests__/components/ErrorBoundary.test.tsx`**:
  - Renders children when no error is thrown.
  - Catches a thrown error from a child component, displays `"WIDGET ERROR"` text, and shows the error message.
  - Renders `fallback` prop instead of the default error UI when provided.
  - Clicking the `"RETRY"` button resets state and re-renders children.
  - Verify `componentDidCatch` logs to `console.error` (spy on `console.error`).

- [ ] Task 4.2. **`src/__tests__/components/Panel.test.tsx`**:
  - With `title='CHART'`: renders `ChartWidget` (mock the widget modules to avoid deep tree).
  - With `title='UNKNOWN_WIDGET'`: renders the `[UNKNOWN_WIDGET WIDGET NOT FOUND]` fallback string.
  - Clicking the panel `div` calls `setFocusedPanel(id)` — verify by reading `focusedPanelAtom` from the test store.
  - When `focusedPanel === id`, border class `border-blue-500` is applied to the container.
  - When not focused, header uses `bg-terminal-gray text-terminal-amber`; when focused uses `bg-blue-900 text-white`.
  - Test every `title` → widget mapping (all 14 valid widget cases + default) by mocking each widget module to render `<div data-testid="WIDGET_NAME" />`.

- [ ] Task 4.3. **`src/__tests__/components/CommandBar.test.tsx`**:
  - Typing into the input produces matching suggestions (prefix matches before includes matches).
  - Empty input produces no suggestions dropdown.
  - ArrowDown/ArrowUp cycle through suggestions; `selectedIdx` wraps around.
  - Tab key completes input with first suggestion.
  - Escape clears input and hides dropdown.
  - Submitting a valid widget command (`CHART`) sets `activeCommandAtom` to `'CHART'` and clears the input.
  - Submitting with a selected suggestion index selects that suggestion's command.
  - Clicking a dropdown item calls `handleSelect` with the correct command.
  - WS indicator shows `'LIVE'` when `wsConnectedAtom` is `true`; `'OFFLINE'` when `false`.
  - Funds are displayed in the format `CASH: ₹X,XX,XXX` when `fundsAtom` is populated.
  - `CMD:` display shows `activeCommandAtom` value or `—` when empty.
  - The `onBlur` handler resets `selectedIdx` after 250ms (use `vi.useFakeTimers()`).

- [ ] Task 4.4. **`src/__tests__/components/TerminalContainer.test.tsx`**:
  - On mount, calls `wsService.connect()`.
  - On unmount, calls `wsService.disconnect()` and the unsubscribe returned by `wsService.onConnectionChange`.
  - When WS connection state changes, `wsConnectedAtom` is updated accordingly.
  - Pressing `Escape` focuses the element with `id="terminal-command-input"`.
  - Pressing `/` focuses the command input and prevents default.
  - When `activeCommandAtom` is set to a valid widget name, `activePanelsAtom[focusedPanel]` is updated to that widget name and `activeCommandAtom` is reset to `''`.
  - When `activeCommandAtom` is set to `'BREAKOUT'` (typo alias), it is normalized to `'BREAKOUTS'`.
  - When `activeCommandAtom` is set to an unknown string (e.g., `'FOOBAR'`), `activePanelsAtom` is NOT updated.
  - When `focusedPanel` points to a panel number exceeding `panelCount`, `focusedPanel` resets to `'panel-1'`.
  - Renders `children` wrapped in `<main>`.

- [ ] Task 4.5. **`src/__tests__/components/GridSystem.test.tsx`** (mock `react-split` and `Panel`):
  - With `panelCount=2`: renders exactly 2 `Panel` components in a single horizontal `Split`.
  - With `panelCount=4`: renders 4 panels in 2 rows × 2 columns.
  - With `panelCount=6`: renders 6 panels in 2 rows × 3 columns.
  - With `panelCount=8`: renders 8 panels in 2 rows × 4 columns.
  - When `panelSizes` is null, uses `createDefaultPanelSizes` output.
  - When `panelSizes` has mismatched row/column counts, falls back to default sizes.
  - Dragging a row split calls `setPanelSizes` with updated `rowSizes` while keeping `colSizes` unchanged.
  - Dragging a column split in row 0 calls `setPanelSizes` with updated `colSizes[0]` while keeping other rows unchanged.

- [ ] Task 4.6. **`src/__tests__/components/LiveTicker.test.tsx`**:
  - Shows `"Loading market data…"` while `movers` query is pending.
  - Once data resolves, renders items combining gainer and loser symbols.
  - Each item displays `NSE:{symbol}` label and the `ltp.toFixed(2)` value.
  - When `tickData` atom has a matching key, the ticker item reflects the live `ltp` over the REST snapshot.
  - On mount, calls `wsService.subscribe` for each symbol with mode `1`.
  - On unmount, calls `wsService.unsubscribe` for each symbol.
  - Duplicate items are rendered (the `[...items, ...items]` ticker pattern) — verify the count is `2 * (gainers + losers)`.

---

### Phase 5 — Widget Component Tests

- [ ] Task 5.1. **`src/__tests__/widgets/MoversWidget.test.tsx`**:
  - Renders `"Loading movers..."` while both queries are pending.
  - Renders `"No data available."` when both result arrays are empty.
  - After data resolves, renders "Top Gainers" and "Top Losers" section headers.
  - Gainer rows render with `text-terminal-green` class; loser rows with `text-terminal-red`.
  - Clicking a row sets `activeSymbolAtom` to that row's symbol and `activeExchangeAtom` to `'NSE'`.
  - Column headers render labels from `COLUMN_LABELS` for the active `moversColumnsAtom` value.

- [ ] Task 5.2. **`src/__tests__/widgets/OrderWidget.test.tsx`**:
  - Initial state syncs symbol and exchange from `activeSymbolAtom`/`activeExchangeAtom`.
  - When `activeSymbolAtom` changes, the symbol input updates.
  - Price and trigger price fields only appear for the correct order types: LIMIT (price only), SL (both), SL-M (trigger only), MARKET (neither).
  - Clicking BUY calls `OpenAlgoClient.placeOrder` with `action: 'BUY'`; clicking SELL calls with `action: 'SELL'`.
  - On successful order, status message shows `"Order TEST001: Order placed"`.
  - On API error, status message shows `text-terminal-red` error text.
  - During submission, both BUY and SELL buttons are disabled.
  - Pressing F1 triggers a BUY order; pressing F2 triggers a SELL order (mock `handleOrder`).
  - Recent orders table renders the last 8 orders from the order book query.
  - Order status color: `complete` → green, `rejected` → red, otherwise amber.

- [ ] Task 5.3. **`src/__tests__/widgets/WatchWidget.test.tsx`**:
  - Renders watchlist selector with options from `watchlistsAtom`.
  - Clicking `+` button opens the create watchlist modal.
  - Create modal validates name: only `[A-Za-z-]+`, max 32 chars; submit button disabled for invalid input.
  - Successful watchlist creation calls `POST /api/watchlists`, closes modal, and switches active watchlist.
  - Typing in the symbol search input triggers `GET /api/py/stockuniverse/search/:query` after 300ms debounce (use `vi.useFakeTimers()`).
  - Selecting from autocomplete dropdown populates the symbol field.
  - Submitting the add-symbol form calls `POST /api/watchlist` and invalidates the watchlist query.
  - Clicking the `✕` remove button calls `DELETE /api/watchlist` with correct `id`.
  - Clicking a row sets `activeSymbolAtom` and `activeExchangeAtom` from that row's item.
  - Clicking a column header sets sort column and default direction; clicking again reverses direction.
  - Sort indicators (`▲`/`▼`) appear on the active sort column header.
  - Null values in `compareValues` sort to the end regardless of direction.
  - Empty watchlist renders `"No symbols. Add one above."`.

- [ ] Task 5.4. **`src/__tests__/widgets/NotifWidget.test.tsx`**:
  - Shows loading state while query is pending.
  - Shows error state with retry button when query fails; clicking retry calls `refetch`.
  - Renders notification rows with badge, symbol, message, and time.
  - `ALL` tab shows all notifications; other tabs filter to their `TAB_TRIGGERS` entries.
  - Clicking a notification row sets `activeSymbolAtom` and `activeExchangeAtom`.
  - Hovering a notification row shows the portal tooltip with trigger description.
  - Clicking the `×` dismiss button calls `DELETE /api/py/notifications/:id`.
  - `CLEAR ALL` button is only visible when there are notifications; clicking it calls `DELETE /api/py/notifications?all=true`.
  - `CLEAR ALL` button is hidden when notification list is empty.
  - Watchlist selector fires a new query when changed.

- [ ] Task 5.5. **`src/__tests__/widgets/ChartWidget.test.tsx`** (mock `lightweight-charts`):
  - Chart container div renders on mount.
  - `createChart` is called once on mount with correct theme colors (black background, amber text).
  - `chart.remove()` is called on unmount.
  - Submitting the symbol form with a new symbol calls `setSymbol` and `setExchange`, updating `activeSymbolAtom`.
  - Clicking an interval button changes the active interval (amber highlight class applied).
  - Loading indicator `"LOADING…"` appears while history query is pending.
  - Error indicator `"API ERR"` appears when history query fails.
  - When `panelId !== focusedPanel`, the symbol label is shown in the toolbar; when focused it is hidden.
  - `handleRefresh` calls `queryClient.invalidateQueries` with the correct query key.
  - On symbol change, `seriesRef.setData([])` is called (verify via the chart mock).
  - On successful history data, `seriesRef.setData(bars)` and `chart.timeScale().fitContent()` are called.
  - A tick from `wsService` for the correct symbol/exchange updates the candle via `seriesRef.update`.
  - A tick for a different symbol is ignored.

- [ ] Task 5.6. **Stub tests for remaining widgets** (`PosWidget`, `SettingsWidget`, `FundamentalsWidget`, `DealsWidget`, `LargedealsWidget`, `BreakoutsWidget`, `NewsWidget`, `AnalysisWidget`, `ScanWidget`, `AnnouncementsWidget`) — each gets a minimal test file that:
  - Renders without crashing (smoke test).
  - Shows loading state while the primary query is pending.
  - Shows error state with appropriate text when the query fails.
  - Renders key data from the MSW fixture response.
  This covers regression protection while keeping test count manageable for the initial harness.

---

### Phase 6 — WebSocket Service Unit Tests

- [ ] Task 6.1. **`src/__tests__/lib/socket.test.ts`** — test `WebSocketService` directly (no component rendering):
  - `connect()` creates a `WebSocket` with `NEXT_PUBLIC_OPENALGO_WS_URL` or the default `ws://localhost:8765`.
  - `connect()` when already open logs and returns without creating a new socket.
  - On `socket.onopen`, immediately sends an `authenticate` message with the fetched API key.
  - On auth success message (`type: 'auth'`), sets `authenticated=true` and notifies connection listeners.
  - On auth success via `status: 'success'`, same behavior.
  - On `socket.onclose`, sets `authenticated=false`, notifies listeners, and schedules reconnect.
  - `subscribe(symbol, exchange, mode)` adds to `subscriptions` map and sends subscribe message if authenticated.
  - `unsubscribe(symbol, exchange, mode)` removes from `subscriptions` map.
  - After reconnect (auth re-confirmed), `resubscribeAll()` sends subscribe for every entry in `subscriptions`.
  - `disconnect()` clears `subscriptions`, closes socket without triggering reconnect, and notifies `false`.
  - `onTick` returns an unsubscribe function that removes the handler from `tickListeners`.
  - `onConnectionChange` returns an unsubscribe function that removes the handler from `connectionListeners`.
  - Backoff: second reconnect delay is `2000ms`; third is `4000ms`; max is `30000ms`.
  - After `maxReconnectAttempts` (10), `scheduleReconnect` does not schedule further reconnects.
  - Use `vi.stubGlobal('WebSocket', ...)` to control socket lifecycle in tests.

---

### Phase 7 — OpenAlgoClient Unit Tests

- [ ] Task 7.1. **`src/__tests__/lib/openalgo.test.ts`** — test `OpenAlgoClient` static methods via MSW:
  - `getFunds()` calls `POST /api/openalgo/funds` and returns typed `FundsData`.
  - `getOrderBook()` calls `POST /api/openalgo/orders` and returns `OrderData[]` plus statistics.
  - `getPositionBook()` calls `POST /api/openalgo/positions`.
  - `placeOrder(params)` calls `POST /api/openalgo/placeorder` with correct body fields.
  - `getHistory(symbol, exchange, interval, start, end)` calls `POST /api/openalgo/history`.
  - When the server returns `status !== 'success'`, the method throws `Error: API Error: <message>`.
  - When the HTTP response is non-2xx, the method throws with the error field from the response body.

---

### Phase 8 — Integration / Behavioural Tests

- [ ] Task 8.1. **`src/__tests__/integration/commandFlow.test.tsx`** — end-to-end command dispatch through `TerminalContainer` + `CommandBar` + `Panel`:
  - Render `TerminalContainer` wrapping `CommandBar` and a single `Panel` (panel-1 focused, showing `CHART` by default).
  - Type `"WATCH"` into the command input and press Enter → verify `activePanelsAtom['panel-1']` becomes `'WATCH'`.
  - Type `"breakout"` (lowercase) → verify panel receives `'BREAKOUTS'` (normalization test).
  - Type an unknown command `"XYZ123"` → verify `activePanelsAtom` is unchanged.

- [ ] Task 8.2. **`src/__tests__/integration/wsConnectionFlow.test.tsx`** — WebSocket connection lifecycle integration:
  - Render `TerminalContainer`; verify `wsService.connect()` is called once.
  - Trigger `onConnectionChange(true)` via the mock helper → verify `wsConnectedAtom` becomes `true` → `CommandBar` renders `'LIVE'` indicator.
  - Trigger `onConnectionChange(false)` → verify `wsConnectedAtom` becomes `false` → `CommandBar` renders `'OFFLINE'`.
  - Unmount `TerminalContainer` → verify `wsService.disconnect()` is called.

- [ ] Task 8.3. **`src/__tests__/integration/symbolNavigation.test.tsx`** — symbol selection cross-widget propagation:
  - Render `WatchWidget` and `ChartWidget` together under shared providers.
  - Simulate clicking a watchlist row (symbol `"INFY"`, exchange `"NSE"`).
  - Verify `activeSymbolAtom` becomes `"INFY"` and `activeExchangeAtom` becomes `"NSE"`.
  - Verify `ChartWidget`'s symbol input reflects `"INFY"` (synced via the `useEffect` on `symbol`/`exchange` atoms).

---

## Verification Criteria

- All pure utility function tests pass with 100% coverage of the functions under test.
- `ErrorBoundary` tests pass for all three paths: normal render, error catch, retry.
- `CommandBar` autocomplete keyboard navigation tests pass including wrap-around and Tab completion.
- `TerminalContainer` command processor correctly handles all valid widget names, `BREAKOUT→BREAKOUTS` alias, and rejects unknown commands.
- `GridSystem` renders the correct panel count for all four `PanelCount` values.
- `Panel` renders all 14 valid widget mappings and the default fallback.
- `OrderWidget` BUY/SELL flows and conditional field visibility tests pass.
- `WatchWidget` sort, add, remove, and watchlist creation tests pass.
- `NotifWidget` tab filtering and dismiss tests pass.
- `ChartWidget` smoke tests pass with mocked `createChart`.
- All 10 remaining widget smoke/stub tests pass (no render crash).
- `WebSocketService` authentication, subscription, reconnect backoff, and max-attempts tests pass.
- `OpenAlgoClient` method tests pass including error path handling.
- The three integration tests (command flow, WS connection, symbol navigation) pass.
- `npm run test` exits with code `0`.
- Coverage report shows ≥ 70% statement coverage on `src/components/` and `src/lib/`.

---

## Potential Risks and Mitigations

1. **Jotai `atomWithStorage` reads `localStorage` on initialisation** — tests running in parallel may share `localStorage` state causing flaky failures.
   Mitigation: Use a fresh Jotai `createStore()` per test via the custom `renderWithProviders` wrapper; additionally call `localStorage.clear()` in `afterEach` in the global setup file.

2. **`WebSocketService` singleton retains state between test runs** — if `connect()` is called in one test and not cleaned up, subsequent tests may see `authenticated=true` or stale subscriptions.
   Mitigation: The `wsService` mock in Task 2.1 replaces the singleton with a fresh object of `vi.fn()` stubs. For the socket unit test (Task 6.1), use `vi.stubGlobal('WebSocket', mockConstructor)` and reset via `vi.unstubAllGlobals()` in `afterEach`.

3. **`lightweight-charts` uses `ResizeObserver` and canvas APIs** — both unavailable in jsdom.
   Mitigation: The module-level mock in Task 2.2 prevents any real `createChart` execution. Additionally, `happy-dom` (Task 1.4) provides a stub `ResizeObserver` that avoids the `ReferenceError` seen in standard jsdom.

4. **`react-split` calls `getBoundingClientRect`** — returns `{ width: 0 }` in test environments causing `NaN` split sizes.
   Mitigation: The module mock in Task 2.3 bypasses `react-split` entirely, rendering children in a plain `<div>`.

5. **TanStack Query's `refetchInterval` causes tests to hang** — periodic refetches keep the test alive after assertions complete.
   Mitigation: Create `QueryClient` with `defaultOptions.queries.refetchInterval: false` and `gcTime: 0` in `renderWithProviders`. Use `vi.useFakeTimers()` in specific tests that need to advance timers.

6. **`NotifWidget` uses `ReactDOM.createPortal` to `document.body`** — the portal renders outside the container returned by `render()`.
   Mitigation: Query the tooltip using `document.body` directly (e.g., `within(document.body).getByText(...)`) in tooltip-specific tests.

7. **`ChartWidget` `useEffect` cleanup calls `chart.remove()` on unmount** — if the mock is not properly structured, this may throw.
   Mitigation: Ensure the `createChart` mock returns an object where all methods are `vi.fn()`, including `remove()`. Verify `chart.remove()` is called in the unmount test explicitly.

---

## Alternative Approaches

1. **Jest instead of Vitest**: Jest with `ts-jest` and `jest-environment-jsdom` is the traditional Next.js choice and has more ecosystem examples. Trade-off: requires Babel or `ts-jest` to handle ESM packages (`jotai`, `@tanstack/react-query`, `lightweight-charts` all ship ESM-first); adds significant `moduleNameMapper` and `transformIgnorePatterns` configuration complexity. Vitest is the better choice for this modern stack.

2. **Playwright Component Testing instead of Vitest**: Playwright's `@playwright/experimental-ct-react` can test components in a real browser, eliminating all jsdom/happy-dom limitations. Trade-off: slower (requires browser launch), harder to isolate from the network, not well-suited for unit-level tests of pure functions and store logic. Suitable as a future addition for visual regression tests of `ChartWidget` and `LiveTicker`, but not for the primary test harness.

3. **Co-located test files (`*.test.tsx` next to source) instead of `src/__tests__/`**: Keeps tests near their source and is a common convention. Trade-off: increases noise in the `src/components/widgets/` directory. The `src/__tests__/` tree approach provides a cleaner separation for this project where all tests are new rather than grandfathered in.
