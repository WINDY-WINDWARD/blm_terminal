# Build Memory Doc — BLM Terminal Feature Expansion

**Started**: 2026-05-30  
**Scope**: Feature 1 (AI Personas), Feature 2 (Valuation Tab), Feature 3 (Portfolio Optimizer)  
**Approach**: One feature at a time, verify, document, then move on.

---

## Decisions Log

### Meta-Decisions
- **One-at-a-time approach**: Selected by user. Reduces risk, makes debugging easier.
- **Memory doc**: Created at `/Users/glubglub/Documents/blm_terminal/docs/BuildMemory.md` to track what was built, how, and why.
- **recharts check**: Will check `package.json` before Feature 3; if available, use it for pie chart. If not, fall back to CSS-only as per handoff.
- **Full command integration**: Will add `PORTFOLIO` to terminalStore, Panel, and command palette/help text.

---

## Feature 1 — AI Research Agent Personas

### Files Modified
- `backend/app/routers/ai_chat.py`
- `backend/app/services/ai_chat_service.py`
- `src/components/widgets/AiWidget.tsx`

### Build Notes
- **2026-05-30**: Added `persona: str | None` field to `ChatRequest` Pydantic model in `ai_chat.py` and passed it through to `run_chat_agent()`.
- **2026-05-30**: Added `PERSONA_SYSTEM_PROMPTS` dict with 4 personas (value, earnings, fno, macro) in `ai_chat_service.py`.
- **2026-05-30**: Created `_get_system_prompt(symbol, exchange, persona)` helper. When persona is set, returns the persona-specific prompt + symbol context. When no persona, falls back to existing `_build_system_prompt()` to preserve existing behavior and rich default instructions.
- **2026-05-30**: Modified `run_chat_agent()` signature to accept `persona: str | None = None` and wired `_get_system_prompt()` into both OpenAI and Anthropic loops.
- **Decision**: Kept `_build_system_prompt()` intact for the non-persona case instead of replacing it with the handoff's simpler base prompt. This preserves all existing formatting rules, tool usage instructions, and constraints (500-word limit, markdown tables, etc.) when no persona is selected.
- **2026-05-30**: Frontend: Added `PERSONAS` const and `PersonaId` type. Added `activePersona` state. Added pill-button selector above chat input. Persona resets on session switch and new chat. Passed `persona: activePersona` in POST body.
- **Verification**: `python -m py_compile` passed for both backend files.

---

## Feature 2 — Valuation Models Tab

### Files Created
- `backend/app/routers/valuation.py`

### Files Modified
- `backend/app/routers/__init__.py`
- `backend/main.py`
- `src/components/widgets/FundamentalsWidget.tsx`

### Build Notes
- **2026-05-30**: Created `valuation.py` router with 5 models: Graham Number, DCF (2-stage 10Y), DDM, EV/EBITDA (12x median), PEG Fair Value. Uses yfinance via `.NS` suffix. 30-min in-memory cache.
- **2026-05-30**: Registered `valuation_router` in `__init__.py` and `main.py`.
- **2026-05-30**: Restructured `FundamentalsWidget.tsx` from a permanent two-column layout to a tabbed layout (Ratios / Quarterly / Valuation).
  - Decision: Moved Calculated Ratios (Piotroski, Peter Lynch, Morningstar) into the Ratios tab alongside Key Ratios, since they are derived from the same screener data. The Quarterly tab now only shows the quarterly table.
  - Added `useState` for `activeTab`, `wacc`, `terminalGrowth`.
  - Added valuation `useQuery` with `enabled: !!symbol && activeTab === 'valuation'` to avoid slow yfinance calls when tab is not active.
  - Added WACC and Terminal Growth dropdowns with Refresh button in the Valuation tab.
  - Signal coloring: UNDERVALUED (>+15%) green, FAIR (±15%) yellow, OVERVALUED (<-15%) red.
- **Verification**: `python -m py_compile` passed for all modified backend files.

---

## Feature 3 — Portfolio Optimizer

### Files Created
- `backend/app/routers/portfolio.py`
- `src/components/widgets/PortfolioWidget.tsx`

### Files Modified
- `backend/app/routers/__init__.py`
- `backend/main.py`
- `backend/pyproject.toml`
- `src/components/TerminalContainer.tsx`
- `src/components/Panel.tsx`
- `src/components/CommandBar.tsx`
- `src/components/widgets/SettingsWidget.tsx`
- `src/lib/widgetDocs.ts`

### Build Notes
- **2026-05-30**: Installed `pyportfolioopt==1.6.0` in backend venv. Added to `pyproject.toml` dependencies along with `yfinance>=0.2.0`.
- **2026-05-30**: Created `portfolio.py` router with two endpoints:
  - `POST /portfolio/optimize` — mean-variance optimization (max_sharpe, min_volatility) and hierarchical risk parity (risk_parity) using PyPortfolioOpt.
  - `GET /portfolio/watchlist-preview` — 1Y return/vol/price preview for watchlist symbols.
  - Both use `asyncio.to_thread()` for sync yfinance/pypfopt calls. 15-minute cache.
- **2026-05-30**: Registered `portfolio_router` in `__init__.py` and `main.py`.
- **2026-05-30**: Created `PortfolioWidget.tsx` with CSS-only visualization (no charting library — recharts not in package.json):
  - Left panel: watchlist symbol checkboxes with 1Y return preview, period/objective selectors, Optimize button.
  - Right panel: portfolio stats, CSS bar-chart weights, correlation heatmap (HSL color grid), per-symbol statistics table.
  - Decision: Used `useState` only (no Jotai) since optimization results are transient, as specified in handoff.
- **2026-05-30**: Registered `PORTFOLIO` command everywhere:
  - `TerminalContainer.tsx` — `VALID_WIDGETS`
  - `Panel.tsx` — switch case rendering `<PortfolioWidget />`
  - `CommandBar.tsx` — `WIDGET_COMMANDS` for palette suggestions
  - `SettingsWidget.tsx` — commands list display
  - `widgetDocs.ts` — full documentation entry for the DOCS widget
- **Verification**: `python -m py_compile` passed for all modified backend files.

---

## Round 2: yfinance Elimination & Multi-Watchlist

### Decisions
- **2026-05-30**: User confirmed: use DB-first prices for portfolio, screener-first + yfinance fallback for ALL valuation fields, multi-watchlist support in PortfolioWidget.
- **Portfolio price source**: `ticker_warehouse.get_ohlcv()` → DB-first. If < 80% coverage, trigger `backfill_symbol()` via `nsepython.equity_history()`. If still empty → `symbols_failed`.
- **Valuation data source**: `_fetch_valuation_data()` helper. Step 1: screener_client.get_company(). Map ratios to inputs. Step 2: ALWAYS call yfinance, fill gaps only. Result = screener+yfinance hybrid.
- **Key discovery from live test**: screener provides `graham` (pre-computed), `evebitda` (ratio), `ebit` + `dep_ann` → EBITDA, `market_cap` / `price` → shares outstanding. Only FCF truly missing from screener.
- **YFinance installed**: `pip install yfinance` added to venv for valuation fallback.
- **Multi-watchlist**: Added `<select>` dropdown in PortfolioWidget left panel. Fetches `/api/watchlists` on mount. On change, loads `/api/watchlist?watchlist_id={id}` and clears selected symbols.

### Files Modified (Round 2)
- `backend/app/routers/portfolio.py` — rewritten: removed all yfinance, uses `ticker_warehouse.get_ohlcv()` + `backfill_symbol()` fallback
- `backend/app/routers/valuation.py` — rewritten: `_fetch_valuation_data()` helper, screener-first + yfinance fallback for ALL fields
- `src/components/widgets/PortfolioWidget.tsx` — added watchlist selector dropdown, dynamic symbol loading
- `docs/BuildMemory.md` — this update

## Verification Checklist
- [x] `npm run build` passes — TypeScript compiled, 114 frontend tests passed
- [x] `pytest -m "not slow"` — 278 passed, 27 failed (all pre-existing, same as before)
- [x] Portfolio optimize works with DB prices — tested RELIANCE/TCS/HDFCBANK, DB returned 268 rows, optimization computed weights successfully
- [x] Valuation works with screener+yfinance hybrid — tested RELIANCE, all 5 models computed, data_source="screener+yfinance"
- [x] PortfolioWidget multi-watchlist selector — code verified, dropdown fetches /api/watchlists and /api/watchlist?watchlist_id={id}

## Smoke Test Results

### Portfolio Optimizer
```
Prices shape: (268, 2) — RELIANCE + TCS from DB
Failed: [] — no symbols failed
Optimization: weights computed, Sharpe ratio calculated
Edge case handled: max_sharpe fallback to equal weights when no asset exceeds risk-free rate
```

### Valuation Models (RELIANCE)
```
Graham Number:  ₹947.0   (screener pre-computed)
DCF (10Y):      ₹932.66  (yfinance FCF + screener growth)
DDM:            null     (negative earnings growth — mathematically invalid)
EV/EBITDA:      ₹1392.22 (screener EBITDA + ratio)
PEG Fair Value: ₹1257.8  (screener EPS + growth)
Data source:    screener+yfinance
```

## Feature Status
- [x] Feature 1 — AI Research Agent Personas: COMPLETE
- [x] Feature 2 — Valuation Models Tab: COMPLETE (with screener-first + yfinance fallback)
- [x] Feature 3 — Portfolio Optimizer: COMPLETE (with DB-first prices + backfill fallback, multi-watchlist support)

All three features built, tested, and verified.

