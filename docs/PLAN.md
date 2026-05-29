# BLM Terminal — Feature Expansion Plan

**Date**: 2026-05-29  
**Scope**: Three new features to improve Indian market trading intelligence  
**Based on**: Clean-room analysis of FinceptTerminal (https://github.com/Fincept-Corporation/FinceptTerminal)

---

## Executive Summary

Three features are being added to the BLM Terminal, ordered by implementation priority:

| # | Feature | Type | Effort |
|---|---------|------|--------|
| 1 | AI Research Agent Personas | Enhancement to AiWidget | Small |
| 2 | Valuation Models Tab | Enhancement to FundamentalsWidget | Medium |
| 3 | Portfolio Optimizer | New Widget + Backend | Large |

---

## Feature 1 — AI Research Agent Personas

### What It Does

Adds four specialist financial analyst personas to the existing `AiWidget`. When a user selects a persona, a detailed system prompt is prepended to the chat that directs the LLM to adopt that analyst's research framework and use the available MCP tools in a focused, disciplined way.

### Personas

**1. Value Analyst** (Graham / Buffett style)
- Focuses on: margin of safety, moat assessment, intrinsic value vs CMP
- Tools it emphasizes: `screener_company`, `get_symbol_data`, `get_change_ranges`, `get_company_news`
- Typical outputs: Graham Number assessment, ROCE/ROE quality check, promoter holding check, red flag identification

**2. Earnings Analyst**
- Focuses on: QoQ/YoY revenue and profit trends, EPS trajectory, earnings quality, surprise history
- Tools it emphasizes: `screener_company`, `get_corporate_filings`, `get_company_news`
- Typical outputs: Quarter-by-quarter analysis, revenue growth sustainability, margin compression/expansion flags

**3. F&O / Derivatives Analyst**
- Focuses on: Options strategy recommendation, IV percentile context, expiry analysis
- Tools it emphasizes: `get_symbol_data`, `get_top_gainers`, `get_top_losers`, `get_volume_gainers`
- Typical outputs: Whether to buy/sell options, CE/PE bias, hedging suggestions, lot size / premium math

**4. Macro / Sector Analyst**
- Focuses on: Sector rotation, FII/DII flows, RBI policy impact, India macro context
- Tools it emphasizes: `list_sectors`, `list_industries`, `get_sector_stocks`, `get_global_news`
- Typical outputs: Which sectors are accumulating/distributing, macro tailwinds/headwinds, positioning advice

### Architecture

**Backend changes**: Minimal. The `ChatRequest` Pydantic model gains a `persona: str | None` field. The `run_chat_agent()` function in `ai_chat_service.py` receives the persona and prepends the appropriate system prompt to the messages list before entering the agentic loop.

**Frontend changes**: `AiWidget.tsx` gets a persona selector row of 4 pill buttons displayed above the chat input. Selecting a persona stores it in local component state and passes it in the POST body. The active persona name is shown as a badge in the chat header. Persona persists only for the current session (not stored in DB — it's just a system prompt injection).

**No DB migrations needed.** The `persona` field is ephemeral — it only affects what system prompt is sent; it is not stored in `chat_sessions`.

### UI Mockup

```
┌─────────────────────────────────────────────────────────┐
│  AI Research  [kimi-k2.5 ▾]                             │
│  ┌──────────┐ ┌───────────┐ ┌─────────┐ ┌──────────┐   │
│  │  Value   │ │ Earnings  │ │  F&O    │ │  Macro   │   │
│  │ Analyst  │ │ Analyst   │ │ Analyst │ │ Analyst  │   │
│  └──────────┘ └───────────┘ └─────────┘ └──────────┘   │
│  [active persona badge shown in header when selected]   │
│                                                         │
│  [Chat history area]                                    │
│                                                         │
│  ┌──────────────────────────────────────────────────┐   │
│  │  Ask anything about RELIANCE...                  │   │
│  └──────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

---

## Feature 2 — Valuation Models Tab in FundamentalsWidget

### What It Does

Adds a third tab "Valuation" inside `FundamentalsWidget` (joining "Ratios" and "Quarterly"). This tab shows multiple automated intrinsic value estimates for the active stock, computed server-side using yfinance financial data.

### Valuation Models Implemented

**1. Graham Number**
```
Graham Number = √(22.5 × EPS_TTM × Book Value Per Share)
```
- Source: `ticker.info` fields `epsTrailingTwelveMonths` and `bookValue`
- Classic Benjamin Graham formula; gives a conservative floor price
- Output: Fair value price + % premium/discount vs CMP

**2. Simplified DCF (10-Year)**
```
Intrinsic Value = Σ(FCF × (1+g)^t / (1+WACC)^t) + Terminal Value / (1+WACC)^10
Terminal Value = FCF_year10 × (1+g_terminal) / (WACC - g_terminal)
```
- Source: `ticker.cashflow` for FCF (Operating CF - CapEx), `ticker.info` for revenue/earnings growth
- Default assumptions (user-adjustable):
  - Growth rate (years 1-5): `min(revenueGrowth, 0.25)` capped at 25%
  - Growth rate (years 6-10): half of stage 1 growth
  - Terminal growth rate: 5% (India nominal GDP-ish)
  - WACC: 12% default (typical Indian large-cap hurdle rate)
- Output: Intrinsic value per share + margin of safety % vs CMP

**3. Dividend Discount Model (DDM)**
```
Fair Value = Dividend_current × (1 + g) / (r - g)
```
- Only shown when dividendYield > 0 and dividendRate > 0
- Source: `ticker.info` fields `dividendRate`, `dividendYield`, `earningsGrowth`
- Growth rate: min(earningsGrowth, 0.15) capped at 15%
- Discount rate: 12% default
- Output: Fair value + % premium/discount vs CMP

**4. EV/EBITDA Peer Valuation**
```
Implied Price = (Sector Median EV/EBITDA × Company EBITDA) / Shares Outstanding
```
- Source: Company EBITDA from `ticker.info`; sector median EV/EBITDA from existing `/api/py/markets/industries` endpoint
- Output: Implied price at sector median multiple

**5. PEG-Based Fair Value**
```
Fair Price = EPS_forward × EPS_growth_rate (Lynch P/E = growth rate rule)
```
- Source: `forwardEps` and `earningsGrowth` from `ticker.info`
- Output: PEG-based fair value

### Backend: New Router `backend/app/routers/valuation.py`

**Endpoint**: `GET /valuation/{symbol}`

**Query params**:
- `wacc: float = 0.12` — discount rate
- `stage1_growth: float | None = None` — override stage 1 DCF growth (auto-computed if omitted)
- `terminal_growth: float = 0.05` — terminal growth rate

**Response schema**:
```python
class ValuationResult(BaseModel):
    symbol: str
    cmp: float                          # current market price
    currency: str                       # INR
    graham_number: float | None
    graham_upside_pct: float | None
    dcf_value: float | None
    dcf_upside_pct: float | None
    dcf_assumptions: dict               # growth rates, WACC used
    ddm_value: float | None
    ddm_upside_pct: float | None
    ev_ebitda_value: float | None
    ev_ebitda_upside_pct: float | None
    peg_value: float | None
    peg_upside_pct: float | None
    data_source: str                    # "yfinance"
    fetched_at: str                     # ISO timestamp
```

**Caching**: 30-minute TTL in-memory cache (same pattern as screener.py). yfinance data is slow to fetch, so caching is essential.

**Error handling**: If yfinance returns no data (symbol not found on Yahoo Finance), return 404. If partial data (e.g. no FCF for DCF), return the models that can be computed and set others to `null`.

### Frontend: New Tab in FundamentalsWidget

`FundamentalsWidget.tsx` gains a tab switcher with three tabs:
1. `Ratios` — existing content (Key Ratios + More section)  
2. `Quarterly` — existing quarterly results table
3. `Valuation` — new tab

**Valuation tab layout**:
```
┌──────────────────────────────────────────────────────────┐
│  Valuation Models          CMP: ₹1,319                   │
│                                                          │
│  WACC [12%▾]  Terminal Growth [5%▾]    [Refresh]        │
│                                                          │
│  ┌──────────────────────────────────────────────────┐   │
│  │ Model          Fair Value   vs CMP   Signal      │   │
│  │ Graham Number  ₹ 1,155      -12.4%   OVERVALUED  │   │
│  │ DCF (10Y)      ₹ 1,580      +19.8%   UNDERVALUED │   │
│  │ DDM            ₹   890      -32.5%   OVERVALUED  │   │
│  │ EV/EBITDA      ₹ 1,440      +9.2%    FAIR        │   │
│  │ PEG Fair Value ₹ 1,438      +9.1%    FAIR        │   │
│  └──────────────────────────────────────────────────┘   │
│                                                          │
│  DCF Assumptions:                                        │
│  Stage 1 growth: 12.5%  Stage 2: 6.25%  Terminal: 5%    │
│  WACC: 12%  Base FCF: ₹1,921 Cr                         │
└──────────────────────────────────────────────────────────┘
```

**Signal coloring**:
- UNDERVALUED (upside > +15%): green
- FAIR (-15% to +15%): yellow/amber
- OVERVALUED (downside > -15%): red

**WACC / terminal growth dropdowns**: Simple select inputs with preset values (WACC: 10%, 11%, 12%, 13%, 14%, 15%; Terminal: 3%, 4%, 5%, 6%, 7%). Changing them triggers a re-fetch with the new query params.

---

## Feature 3 — Portfolio Optimizer Widget

### What It Does

A new `PortfolioWidget` that lets users select stocks from their watchlist, specify a lookback period, choose an optimization objective, and receive statistically optimal portfolio weights using Modern Portfolio Theory. Built with `pyportfolioopt`.

### Backend: New Router `backend/app/routers/portfolio.py`

**Endpoint 1**: `POST /portfolio/optimize`

**Request body**:
```python
class PortfolioOptimizeRequest(BaseModel):
    symbols: list[str]          # e.g. ["RELIANCE", "TCS", "HDFCBANK"]
    period: str = "2y"          # "1y" | "2y" | "3y"
    objective: str = "max_sharpe"  # "max_sharpe" | "min_volatility" | "risk_parity"
    risk_free_rate: float = 0.065  # RBI repo rate approx
```

**Response**:
```python
class PortfolioOptimizeResult(BaseModel):
    weights: dict[str, float]              # {"RELIANCE": 0.32, "TCS": 0.28, ...}
    expected_annual_return: float          # e.g. 0.156 (15.6%)
    expected_annual_volatility: float      # e.g. 0.187 (18.7%)
    sharpe_ratio: float                    # e.g. 1.23
    correlation_matrix: dict[str, dict[str, float]]
    individual_stats: dict[str, dict]      # per symbol: return, volatility, sharpe
    period_used: str
    objective_used: str
    computed_at: str
```

**Implementation notes**:
- Fetch historical daily prices via `yf.download([s + ".NS" for s in symbols], period=period)`
- Compute log returns
- Use `pypfopt.expected_returns.mean_historical_return()` and `pypfopt.risk_models.sample_cov()`
- For `max_sharpe`: `EfficientFrontier.max_sharpe(risk_free_rate=risk_free_rate)`
- For `min_volatility`: `EfficientFrontier.min_volatility()`
- For `risk_parity`: Use `pypfopt.HRPOpt` (Hierarchical Risk Parity)
- Clean weights with `ef.clean_weights()` to eliminate tiny allocations
- Minimum 3 symbols required, maximum 30

**Endpoint 2**: `GET /portfolio/watchlist-preview`
- Takes watchlist symbols, returns per-symbol 1Y return, volatility, and current price
- Used by frontend to show a preview before running full optimization
- Cached 15 minutes

**Dependency**: Add `pyportfolioopt` and `yfinance` to `backend/pyproject.toml` dependencies.

### Frontend: New `PortfolioWidget.tsx`

**Widget command**: `PORTFOLIO` (add to terminalStore and command palette)

**Layout — Three-panel design**:

```
┌─────────────────────────────────────────────────────────────────┐
│  Portfolio Optimizer                                            │
├─────────────────┬───────────────────────────────────────────────┤
│  STOCKS         │  RESULTS                                      │
│                 │                                               │
│  From Watchlist │  ┌─────────────────────────────────────────┐  │
│  ☑ RELIANCE     │  │  Optimal Weights (Max Sharpe)           │  │
│  ☑ TCS          │  │  ┌──────────────────────────────────┐   │  │
│  ☑ HDFCBANK     │  │  │  [PIE CHART]                     │   │  │
│  ☑ INFY         │  │  │  RELIANCE  32% ████████          │   │  │
│  ☐ WIPRO        │  │  │  TCS       28% ███████           │   │  │
│  ☐ AXISBANK     │  │  │  HDFCBANK  25% ██████            │   │  │
│                 │  │  │  INFY      15% ████              │   │  │
│  Period:        │  │  └──────────────────────────────────┘   │  │
│  [2 Years  ▾]   │  │                                         │  │
│                 │  │  Expected Return:    15.6% p.a.         │  │
│  Objective:     │  │  Expected Volatility: 18.7% p.a.       │  │
│  [Max Sharpe ▾] │  │  Sharpe Ratio:        1.23             │  │
│                 │  └─────────────────────────────────────────┘  │
│  [Optimize]     │                                               │
│                 │  ┌─────────────────────────────────────────┐  │
│                 │  │  Correlation Matrix (heatmap)           │  │
│                 │  │  [color grid]                           │  │
│                 │  └─────────────────────────────────────────┘  │
└─────────────────┴───────────────────────────────────────────────┘
```

**State management**: Local `useState` only — no Jotai atoms needed (optimization results are transient). Watchlist symbols loaded via `useQuery` on mount.

**Visualization**:
- Weight distribution: simple horizontal bar chart built with CSS (no charting library dependency)
- Correlation heatmap: `<div>` grid with background-color scaled from green (negative correlation) to red (positive), white at zero
- No external charting library required (keeps bundle size small)

---

## Implementation Order & Dependencies

```
Feature 1 (AI Personas)
  ├── backend: modify ai_chat_service.py + ai_chat.py   [~2h]
  └── frontend: modify AiWidget.tsx                     [~2h]

Feature 2 (Valuation Tab)
  ├── backend: new valuation.py router                  [~4h]
  │   └── requires: yfinance in venv (already installed for docs research)
  ├── backend: register router in __init__.py + main.py [~15min]
  └── frontend: modify FundamentalsWidget.tsx           [~3h]

Feature 3 (Portfolio Optimizer)
  ├── backend: pip install pyportfolioopt               [~5min]
  ├── backend: new portfolio.py router                  [~5h]
  ├── backend: register router in __init__.py + main.py [~15min]
  └── frontend: new PortfolioWidget.tsx                 [~5h]
      └── requires: add PORTFOLIO command to terminalStore.ts
```

---

## Non-Goals (Explicitly Out of Scope)

- Real-time options chain / OI data (NSE F&O live data requires paid APIs)
- Backtesting engine (separate large project)
- India VIX feed
- QuantStats full tearsheet (can be added later as backend report endpoint)
- RBI/macro data endpoints (low immediate trading utility vs effort)

---

## Testing Notes

- **yfinance availability**: The backend venv already has yfinance installed (`pip install yfinance` was run during research)
- **pyportfolioopt install**: `pip install pyportfolioopt` in `backend/` venv before running Feature 3 backend
- **screener.in session**: Features 1 and 2 do not require screener.in auth. Feature 2 uses yfinance only.
- **Build check**: Run `npm run build` from repo root after frontend changes to catch TypeScript errors before shipping
