> **ARCHIVED** — This document describes a completed implementation. It is kept for historical reference only and is no longer maintained.
> Active codebase conventions and guidelines can be found in [AGENTS.md](file:///d:/500GB/p1/Projects/blm_terminal/AGENTS.md) and [SUMMARY.md](file:///d:/500GB/p1/Projects/blm_terminal/docs/archive/SUMMARY.md).

---

# BLM Terminal — Agent Implementation Handoff

**For**: AI coding agent  
**Active implementation locations**:
- AI Personas: [AiWidget.tsx](file:///d:/500GB/p1/Projects/blm_terminal/src/components/widgets/AiWidget.tsx), [ai_chat.py](file:///d:/500GB/p1/Projects/blm_terminal/backend/app/routers/ai_chat.py)
- Valuation Models: [ValuationWidget.tsx](file:///d:/500GB/p1/Projects/blm_terminal/src/components/widgets/ValuationWidget.tsx), [valuation.py](file:///d:/500GB/p1/Projects/blm_terminal/backend/app/routers/valuation.py)
- Portfolio Optimizer: [PortfolioWidget.tsx](file:///d:/500GB/p1/Projects/blm_terminal/src/components/widgets/PortfolioWidget.tsx), [portfolio.py](file:///d:/500GB/p1/Projects/blm_terminal/backend/app/routers/portfolio.py)

---

## Project Architecture Quick Reference

```
blm_terminal/
├── src/                          # Next.js 16 App Router frontend
│   ├── app/api/py/[...path]/     # Universal proxy to FastAPI backend
│   ├── components/widgets/       # One file per widget, 'use client' first line
│   ├── lib/                      # utils, socket, api-config
│   └── store/terminalStore.ts    # All Jotai atoms
├── backend/                      # FastAPI Python backend
│   ├── main.py                   # App entry, router registration, migrations
│   ├── app/
│   │   ├── routers/              # One file per domain, register in __init__.py
│   │   ├── services/             # Business logic
│   │   ├── models/               # SQLAlchemy ORM models
│   │   ├── config.py             # Settings (pydantic BaseSettings)
│   │   ├── database.py           # AsyncSessionLocal, get_db, Base
│   │   └── mcp_server.py         # MCP tools (docstrings auto-sync to AI tools)
│   └── pyproject.toml            # Python deps
└── docs/
    ├── PLAN.md                   # Feature plan (read this)
    └── HANDOFF.md                # This file
```

**Frontend dev server**: `npm run dev` from repo root  
**Backend dev server**: `cd backend && source .venv/bin/activate && uvicorn main:app --reload --port 4455`  
**Build check**: `npm run build` (runs TypeScript compiler — catch errors before finishing)  
**Python tests**: `cd backend && pytest -m "not slow"`

---

## Critical Conventions (must follow exactly)

### TypeScript / React
- `'use client';` **must be the very first line** of every widget file
- Props as inline `interface` above the component, not as type alias
- Use `cn()` from `@/lib/utils` for conditional classNames
- Data fetching: **only** `useQuery` / `useMutation` from `@tanstack/react-query` — never raw `useEffect + useState` for data
- Errors from proxy: `data.error` field on JSON response
- `import type` for type-only imports
- Import order: 1) react/next, 2) third-party, 3) `@/` internal, 4) `./` relative

### Python
- Async-first: every route handler is `async def`
- `httpx.AsyncClient` for outbound HTTP (never `requests`)
- Pydantic v2 schemas
- `catch (err: unknown)` pattern in TypeScript; `except Exception as exc:` in Python
- All new routers: `router = APIRouter(prefix="/...", tags=[...])`
- Register new routers in **both** `backend/app/routers/__init__.py` AND `backend/main.py`

### API call pattern from frontend
All backend calls go through the Next.js proxy at `/api/py/`. Examples:
- `fetch('/api/py/screener/company/RELIANCE')` → FastAPI `GET /api/screener/company/RELIANCE`
- `fetch('/api/py/valuation/RELIANCE')` → FastAPI `GET /api/valuation/RELIANCE`
- `fetch('/api/py/portfolio/optimize', { method: 'POST', body: ... })` → FastAPI `POST /api/portfolio/optimize`

The proxy (`src/app/api/py/[...path]/route.ts`) handles SSE passthrough, JSON, all methods automatically.

---

## Feature 1: AI Research Agent Personas

### Files to modify

1. `backend/app/routers/ai_chat.py`
2. `backend/app/services/ai_chat_service.py`
3. `src/components/widgets/AiWidget.tsx`

### Step 1 — Backend: Add `persona` field to `ChatRequest`

In `backend/app/routers/ai_chat.py`, modify the `ChatRequest` Pydantic model:

```python
class ChatRequest(BaseModel):
    messages: list[ChatMessageSchema] = Field(...)
    symbol: str = Field(default="RELIANCE")
    exchange: str = Field(default="NSE")
    model: str = Field(default="kimi-k2.5")
    session_id: int | None = Field(default=None)
    persona: str | None = Field(default=None, description="Optional analyst persona key.")
```

In the `chat()` route handler, pass `persona` through to `run_chat_agent()`:

```python
async for chunk in run_chat_agent(
    messages=messages,
    symbol=symbol,
    exchange=exchange,
    model=request.model,
    persona=request.persona,   # ADD THIS
):
```

### Step 2 — Backend: Persona system prompts in `ai_chat_service.py`

Add this dict and helper near the top of `ai_chat_service.py` (after the constants block):

```python
# ---------------------------------------------------------------------------
# Analyst persona system prompts
# ---------------------------------------------------------------------------

PERSONA_SYSTEM_PROMPTS: dict[str, str] = {
    "value": """You are a disciplined value investor analyst in the tradition of Benjamin Graham and Warren Buffett, specialising in NSE-listed Indian equities.

Your analysis framework:
1. QUALITY CHECK: Assess ROCE (>15% is good), ROE (>15% is good), Debt-to-Equity (<1 is preferred), operating cash flow vs net profit consistency. Use screener_company and get_symbol_data tools.
2. MOAT ASSESSMENT: Does the company have pricing power, switching costs, network effects, or cost advantages? Use sector/industry context from list_sectors and get_industry_stocks.
3. INTRINSIC VALUE: Calculate Graham Number (√(22.5 × EPS × Book Value)). Compare to current price. Assess margin of safety.
4. MANAGEMENT: Check promoter holding %, pledge %, insider transactions via screener_trades.
5. GROWTH CONTEXT: 5-year revenue and profit CAGR, Piotroski F-Score.
6. RED FLAGS: Declining ROCE, rising debt, promoter pledging >20%, frequent equity dilution, poor cash conversion.

Always cite the specific data you retrieved. State your conclusion: BUY / HOLD / AVOID with clear reasoning. Be intellectually honest — if data is insufficient, say so. Do not confuse activity with productivity.""",

    "earnings": """You are a forensic earnings analyst specialising in NSE-listed Indian companies.

Your analysis framework:
1. HEADLINE NUMBERS: Revenue QoQ and YoY growth, Net Profit QoQ and YoY growth, EPS trend. Use screener_company for quarterly data and get_corporate_filings for detailed filings.
2. QUALITY OF EARNINGS: Is profit growth driven by operating leverage or one-time items? Check other income vs operating profit ratio. Use get_company_news to check for exceptional items.
3. MARGIN ANALYSIS: Gross margin, EBITDA margin, PAT margin trends — expanding or contracting?
4. REVENUE SUSTAINABILITY: Is revenue growth organic or acquisition-driven? Segment-wise breakdown if available.
5. WORKING CAPITAL: Debtor days, inventory days — are they rising (bad sign)?
6. GUIDANCE / EXPECTATIONS: Any management guidance in recent news? Use get_company_news for analyst commentary.
7. EARNINGS SURPRISE: Compare actual vs street estimates if available.

Be specific about which quarters you are comparing. Flag any accounting concerns. State whether the earnings trend is IMPROVING / STABLE / DETERIORATING.""",

    "fno": """You are an experienced F&O (Futures & Options) derivatives analyst for NSE Indian markets.

Your analysis framework:
1. TREND ASSESSMENT: Is the stock in an uptrend, downtrend, or range? Use get_change_ranges for 1W/1M/3M/6M/1Y returns and get_symbol_data for 52-week high/low context.
2. VOLUME & MOMENTUM: Use get_volume_gainers and check if the stock shows unusual volume. Use get_top_gainers/get_top_losers for intraday momentum context.
3. OPTIONS STRATEGY RECOMMENDATION based on your view:
   - Bullish + low volatility expectation: Bull Call Spread or naked Call Buy
   - Bearish + high volatility expectation: Bear Put Spread or Put Buy
   - Neutral + range-bound: Short Strangle or Iron Condor
   - Directional with hedge: Covered Call or Protective Put
4. RISK MANAGEMENT: Always state maximum loss, maximum profit, breakeven points for the strategy.
5. EXPIRY SELECTION: Weekly vs monthly expiry considerations based on time horizon.
6. POSITION SIZING: Suggest allocation as % of capital, not absolute amounts.

Note: You do not have live IV or options chain data. Base recommendations on price trend and momentum. Always remind the user to verify current option premiums before trading. F&O trading involves substantial risk of loss.""",

    "macro": """You are a macro and sector rotation analyst focused on Indian equity markets.

Your analysis framework:
1. MARKET BREADTH: Use list_sectors to check advance/decline ratios, sentiment labels, and earnings YoY% across all sectors. Identify which sectors are leading vs lagging.
2. SECTOR MOMENTUM: Use get_sector_stocks for the top 2-3 sectors showing bullish sentiment. Check price change and market cap trends.
3. INDIA MACRO CONTEXT from get_global_news:
   - RBI monetary policy stance (hawkish/dovish) and repo rate direction
   - INR/USD movement and FII flow implications
   - Crude oil prices (high crude = negative for India as a net importer)
   - US Fed policy (affects FII flows into emerging markets)
   - India GDP and IIP data
4. SECTOR ROTATION THESIS: Which sectors benefit from the current macro environment?
   - Rate cuts → Banking, Real Estate, Rate-sensitive sectors
   - High crude → Oil & Gas producers gain, Aviation/Paint lose
   - Weak INR → IT exporters gain, importers lose
   - Strong capex cycle → Capital Goods, Infrastructure, Cement
5. POSITIONING: State which 2-3 sectors to overweight and which to underweight with clear macro rationale.

Use get_global_news with threat_level filters to identify macro risks. Be explicit about the difference between short-term (1-3 months) and medium-term (6-12 months) views.""",
}


def _get_system_prompt(symbol: str, exchange: str, persona: str | None) -> str:
    """Build the system prompt, optionally prepending a persona definition."""
    base = (
        f"You are a financial analyst assistant for the BLM Terminal, an Indian equity market "
        f"research platform. The user is currently viewing {symbol} on {exchange}. "
        f"You have access to real-time NSE market tools. Use them proactively to give "
        f"data-driven answers. Always cite the specific data you retrieve."
    )
    if persona and persona in PERSONA_SYSTEM_PROMPTS:
        return PERSONA_SYSTEM_PROMPTS[persona] + f"\n\nCurrent symbol context: {symbol} on {exchange}."
    return base
```

### Step 3 — Backend: Wire system prompt into agentic loop

Find the `run_chat_agent()` function signature in `ai_chat_service.py` and add the `persona` parameter:

```python
async def run_chat_agent(
    messages: list[dict[str, str]],
    symbol: str,
    exchange: str,
    model: str,
    persona: str | None = None,   # ADD THIS
) -> AsyncGenerator[str, None]:
```

Inside `run_chat_agent()`, find where the system message is built and prepend it to the messages list. The exact implementation depends on how the current function handles the system prompt — look for where `messages` is assembled before being sent to the LLM API. Add:

```python
system_content = _get_system_prompt(symbol, exchange, persona)
# Prepend system message (only if messages don't already start with one)
if not messages or messages[0].get("role") != "system":
    messages = [{"role": "system", "content": system_content}] + messages
```

Do this **before** the first `_run_openai_loop` or `_run_anthropic_loop` call.

### Step 4 — Frontend: Persona selector in `AiWidget.tsx`

Add near the top of the file (after imports):

```typescript
const PERSONAS = [
  { id: 'value',    label: 'Value Analyst',    description: 'Graham/Buffett framework' },
  { id: 'earnings', label: 'Earnings Analyst',  description: 'QoQ/YoY earnings forensics' },
  { id: 'fno',      label: 'F&O Analyst',       description: 'Options strategy & derivatives' },
  { id: 'macro',    label: 'Macro Analyst',     description: 'Sector rotation & India macro' },
] as const;

type PersonaId = (typeof PERSONAS)[number]['id'];
```

In the `AiWidget` component, add state:

```typescript
const [activePersona, setActivePersona] = useState<PersonaId | null>(null);
```

Add a persona selector bar in the JSX, **above the chat input area** (find the input area in the existing component and place this just above it):

```tsx
{/* Persona selector */}
<div className="flex gap-1 px-2 py-1.5 border-t border-white/5 flex-wrap">
  {PERSONAS.map((p) => (
    <button
      key={p.id}
      title={p.description}
      onClick={() => setActivePersona(prev => prev === p.id ? null : p.id)}
      className={cn(
        'px-2 py-0.5 rounded text-[10px] font-medium border transition-colors',
        activePersona === p.id
          ? 'bg-blue-500/20 border-blue-400/50 text-blue-300'
          : 'bg-white/5 border-white/10 text-white/40 hover:text-white/70 hover:border-white/20'
      )}
    >
      {p.label}
    </button>
  ))}
  {activePersona && (
    <span className="ml-auto text-[10px] text-blue-400/70 self-center pr-1">
      {PERSONAS.find(p => p.id === activePersona)?.description}
    </span>
  )}
</div>
```

Find where the `POST /api/py/ai/chat` fetch is made (look for the `ChatRequest` body construction) and add `persona`:

```typescript
body: JSON.stringify({
  messages: ...,
  symbol: ...,
  exchange: ...,
  model: ...,
  session_id: ...,
  persona: activePersona,   // ADD THIS
}),
```

Reset persona when switching sessions:
```typescript
// In the session switch handler, add:
setActivePersona(null);
```

---

## Feature 2: Valuation Models Tab

### Files to create

- `backend/app/routers/valuation.py` — new file

### Files to modify

- `backend/app/routers/__init__.py`
- `backend/main.py`
- `src/components/widgets/FundamentalsWidget.tsx`

### Step 1 — Backend: Create `backend/app/routers/valuation.py`

```python
"""Valuation models router — Graham Number, DCF, DDM, EV/EBITDA, PEG.

All models use yfinance data via the .NS suffix for NSE symbols.
Results are cached for 30 minutes to avoid repeated slow yfinance fetches.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/valuation", tags=["valuation"])

# ---------------------------------------------------------------------------
# 30-minute in-memory cache (same pattern as screener.py)
# ---------------------------------------------------------------------------

_cache: dict[str, tuple[float, Any]] = {}
_CACHE_TTL = 1800  # 30 minutes


def _cache_get(key: str) -> Any | None:
    entry = _cache.get(key)
    if entry and (time.time() - entry[0]) < _CACHE_TTL:
        return entry[1]
    return None


def _cache_set(key: str, value: Any) -> None:
    _cache[key] = (time.time(), value)


# ---------------------------------------------------------------------------
# Response schema
# ---------------------------------------------------------------------------


class DcfAssumptions(BaseModel):
    base_fcf_cr: float | None       # Base FCF in Crores INR
    stage1_growth_pct: float        # % e.g. 12.5
    stage2_growth_pct: float        # % e.g. 6.25
    terminal_growth_pct: float      # % e.g. 5.0
    wacc_pct: float                 # % e.g. 12.0
    projection_years: int = 10


class ValuationResult(BaseModel):
    symbol: str
    cmp: float | None
    currency: str = "INR"

    graham_number: float | None = None
    graham_upside_pct: float | None = None

    dcf_value: float | None = None
    dcf_upside_pct: float | None = None
    dcf_assumptions: DcfAssumptions | None = None

    ddm_value: float | None = None
    ddm_upside_pct: float | None = None

    ev_ebitda_value: float | None = None
    ev_ebitda_upside_pct: float | None = None

    peg_value: float | None = None
    peg_upside_pct: float | None = None

    data_source: str = "yfinance"
    fetched_at: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _upside(fair: float, cmp: float) -> float | None:
    if fair is None or cmp is None or cmp == 0:
        return None
    return round((fair - cmp) / cmp * 100, 2)


def _graham_number(eps: float | None, book_value: float | None) -> float | None:
    """Benjamin Graham formula: √(22.5 × EPS × Book Value Per Share)."""
    if eps is None or book_value is None or eps <= 0 or book_value <= 0:
        return None
    import math
    return round(math.sqrt(22.5 * eps * book_value), 2)


def _dcf_value(
    fcf_annual: float | None,    # in INR (not Cr) per share
    stage1_g: float,             # decimal e.g. 0.125
    wacc: float,                 # decimal e.g. 0.12
    terminal_g: float,           # decimal e.g. 0.05
    years: int = 10,
) -> float | None:
    """Simplified 2-stage DCF returning intrinsic value per share."""
    if fcf_annual is None or fcf_annual <= 0:
        return None
    if wacc <= terminal_g:
        return None  # Gordon Growth Model breaks down

    stage2_g = stage1_g / 2
    pv = 0.0
    fcf = fcf_annual
    for t in range(1, years + 1):
        g = stage1_g if t <= 5 else stage2_g
        fcf = fcf * (1 + g)
        pv += fcf / (1 + wacc) ** t

    # Terminal value at year 10
    terminal_fcf = fcf * (1 + terminal_g)
    terminal_value = terminal_fcf / (wacc - terminal_g)
    pv += terminal_value / (1 + wacc) ** years

    return round(pv, 2)


def _ddm_value(
    dividend: float | None,       # annual dividend per share
    growth: float,                # decimal growth rate
    discount_rate: float,         # decimal discount rate
) -> float | None:
    """Gordon Growth DDM."""
    if dividend is None or dividend <= 0:
        return None
    effective_growth = min(growth, 0.15)  # cap at 15%
    if discount_rate <= effective_growth:
        return None
    return round(dividend * (1 + effective_growth) / (discount_rate - effective_growth), 2)


# ---------------------------------------------------------------------------
# Main fetch function (runs yfinance in thread pool — it's sync)
# ---------------------------------------------------------------------------


def _fetch_yfinance(symbol: str) -> dict:
    """Fetch yfinance info synchronously. Run via asyncio.to_thread."""
    import yfinance as yf
    ticker = yf.Ticker(f"{symbol}.NS")
    info = ticker.info or {}

    # Free cash flow from cashflow statement
    fcf_per_share = None
    try:
        cf = ticker.cashflow
        if cf is not None and not cf.empty:
            ocf_row = cf.loc["Operating Cash Flow"] if "Operating Cash Flow" in cf.index else None
            capex_row = cf.loc["Capital Expenditure"] if "Capital Expenditure" in cf.index else None
            if ocf_row is not None and capex_row is not None:
                # Use most recent year (first column)
                ocf = float(ocf_row.iloc[0])
                capex = float(capex_row.iloc[0])  # capex is negative in yfinance
                fcf_total = ocf + capex           # capex already negative, so this is OCF - abs(capex)
                shares = info.get("sharesOutstanding")
                if shares and shares > 0:
                    fcf_per_share = fcf_total / shares
    except Exception:
        pass

    return {
        "info": info,
        "fcf_per_share": fcf_per_share,
    }


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@router.get("/{symbol}", response_model=ValuationResult)
async def get_valuation(
    symbol: str,
    wacc: float = Query(default=0.12, ge=0.05, le=0.30, description="Weighted avg cost of capital (decimal, e.g. 0.12)"),
    terminal_growth: float = Query(default=0.05, ge=0.02, le=0.10, description="Terminal growth rate (decimal)"),
    stage1_growth: float | None = Query(default=None, description="Override stage 1 DCF growth. Auto-computed if omitted."),
) -> ValuationResult:
    """Return intrinsic value estimates for an NSE stock using multiple valuation models."""
    symbol = symbol.upper()
    cache_key = f"{symbol}:{wacc}:{terminal_growth}:{stage1_growth}"

    cached = _cache_get(cache_key)
    if cached:
        return cached

    # Fetch yfinance data in thread pool (yfinance is sync)
    try:
        data = await asyncio.to_thread(_fetch_yfinance, symbol)
    except Exception as exc:
        logger.error("yfinance fetch failed for %s: %s", symbol, exc)
        raise HTTPException(status_code=502, detail=f"yfinance fetch failed: {exc}")

    info = data["info"]
    fcf_per_share = data["fcf_per_share"]

    if not info or info.get("quoteType") not in ("EQUITY", "equity"):
        # Check a basic field — if empty dict or wrong type, symbol not found
        if not info.get("currentPrice") and not info.get("regularMarketPrice"):
            raise HTTPException(status_code=404, detail=f"Symbol {symbol} not found on Yahoo Finance (.NS)")

    cmp: float | None = info.get("currentPrice") or info.get("regularMarketPrice")
    eps: float | None = info.get("epsTrailingTwelveMonths")
    book_value: float | None = info.get("bookValue")
    dividend_rate: float | None = info.get("dividendRate")
    earnings_growth: float | None = info.get("earningsGrowth")  # decimal
    revenue_growth: float | None = info.get("revenueGrowth")    # decimal
    forward_eps: float | None = info.get("forwardEps")
    shares_outstanding: float | None = info.get("sharesOutstanding")
    enterprise_value: float | None = info.get("enterpriseValue")
    ebitda: float | None = info.get("ebitda")

    # Graham Number
    graham = _graham_number(eps, book_value)

    # DCF
    if stage1_growth is None:
        # Auto-compute: use revenue growth capped at 25%, floor at 5%
        raw_g = revenue_growth if revenue_growth is not None else (earnings_growth or 0.10)
        auto_g = max(0.05, min(0.25, raw_g))
    else:
        auto_g = max(0.01, min(0.30, stage1_growth))

    dcf = _dcf_value(
        fcf_annual=fcf_per_share,
        stage1_g=auto_g,
        wacc=wacc,
        terminal_g=terminal_growth,
    )
    dcf_assumptions = DcfAssumptions(
        base_fcf_cr=round(fcf_per_share * (shares_outstanding or 0) / 1e7, 2) if fcf_per_share and shares_outstanding else None,
        stage1_growth_pct=round(auto_g * 100, 2),
        stage2_growth_pct=round(auto_g / 2 * 100, 2),
        terminal_growth_pct=round(terminal_growth * 100, 2),
        wacc_pct=round(wacc * 100, 2),
    )

    # DDM
    effective_eg = earnings_growth if earnings_growth is not None else 0.10
    ddm = _ddm_value(dividend=dividend_rate, growth=effective_eg, discount_rate=wacc)

    # EV/EBITDA implied price
    # We don't have sector median here, so use a simple 12x multiple as NSE large-cap average
    # Frontend can show this with a note
    ev_ebitda_value = None
    if ebitda and shares_outstanding and ebitda > 0:
        NSE_MEDIAN_EV_EBITDA = 12.0
        implied_ev = NSE_MEDIAN_EV_EBITDA * ebitda
        net_debt = (info.get("totalDebt") or 0) - (info.get("totalCash") or 0)
        implied_equity = implied_ev - net_debt
        if implied_equity > 0 and shares_outstanding > 0:
            ev_ebitda_value = round(implied_equity / shares_outstanding, 2)

    # PEG Fair Value: Forward EPS × EPS growth rate (as P/E = growth rule)
    peg_value = None
    if forward_eps and earnings_growth and earnings_growth > 0:
        lynch_pe = earnings_growth * 100  # growth rate as P/E (Lynch rule)
        peg_value = round(forward_eps * lynch_pe, 2)

    result = ValuationResult(
        symbol=symbol,
        cmp=cmp,
        graham_number=graham,
        graham_upside_pct=_upside(graham, cmp) if cmp else None,
        dcf_value=dcf,
        dcf_upside_pct=_upside(dcf, cmp) if cmp else None,
        dcf_assumptions=dcf_assumptions,
        ddm_value=ddm,
        ddm_upside_pct=_upside(ddm, cmp) if cmp else None,
        ev_ebitda_value=ev_ebitda_value,
        ev_ebitda_upside_pct=_upside(ev_ebitda_value, cmp) if cmp else None,
        peg_value=peg_value,
        peg_upside_pct=_upside(peg_value, cmp) if cmp else None,
        fetched_at=datetime.now(timezone.utc).isoformat(),
    )

    _cache_set(cache_key, result)
    return result
```

### Step 2 — Backend: Register the new router

**In `backend/app/routers/__init__.py`**, add:
```python
from app.routers.valuation import router as valuation_router
```
And add `"valuation_router"` to `__all__`.

**In `backend/main.py`**, add to the import block:
```python
from app.routers import (
    ...existing imports...,
    valuation_router,
)
```
And in the router registration section (where all `app.include_router(...)` calls are made):
```python
app.include_router(valuation_router, prefix="/api")
```

### Step 3 — Frontend: Add Valuation tab to `FundamentalsWidget.tsx`

**Add types** near the top of `FundamentalsWidget.tsx` (after existing type definitions):

```typescript
interface DcfAssumptions {
  base_fcf_cr: number | null;
  stage1_growth_pct: number;
  stage2_growth_pct: number;
  terminal_growth_pct: number;
  wacc_pct: number;
  projection_years: number;
}

interface ValuationResult {
  symbol: string;
  cmp: number | null;
  currency: string;
  graham_number: number | null;
  graham_upside_pct: number | null;
  dcf_value: number | null;
  dcf_upside_pct: number | null;
  dcf_assumptions: DcfAssumptions | null;
  ddm_value: number | null;
  ddm_upside_pct: number | null;
  ev_ebitda_value: number | null;
  ev_ebitda_upside_pct: number | null;
  peg_value: number | null;
  peg_upside_pct: number | null;
  fetched_at: string;
}
```

**Add WACC/terminal growth state** inside the `FundamentalsWidget` component:
```typescript
const [activeTab, setActiveTab] = useState<'ratios' | 'quarterly' | 'valuation'>('ratios');
const [wacc, setWacc] = useState(0.12);
const [terminalGrowth, setTerminalGrowth] = useState(0.05);
```

**Add valuation query** (alongside the existing screener and morningstar queries):
```typescript
const { data: valuationData, isLoading: valuationLoading, refetch: refetchValuation } = useQuery<ValuationResult>({
  queryKey: ['valuation', symbol, wacc, terminalGrowth],
  queryFn: async () => {
    const res = await fetch(`/api/py/valuation/${symbol}?wacc=${wacc}&terminal_growth=${terminalGrowth}`);
    if (!res.ok) throw new Error('Valuation fetch failed');
    return res.json();
  },
  enabled: !!symbol && activeTab === 'valuation',
  staleTime: 1000 * 60 * 30,
});
```

**Add tab switcher** in the JSX header area (find where the widget title is rendered):
```tsx
{/* Tab switcher */}
<div className="flex gap-0 border-b border-white/5 mb-2">
  {(['ratios', 'quarterly', 'valuation'] as const).map((tab) => (
    <button
      key={tab}
      onClick={() => setActiveTab(tab)}
      className={cn(
        'px-3 py-1 text-[10px] uppercase tracking-wider font-medium capitalize transition-colors',
        activeTab === tab
          ? 'border-b-2 border-blue-400 text-blue-300'
          : 'text-white/30 hover:text-white/60'
      )}
    >
      {tab}
    </button>
  ))}
</div>
```

**Wrap existing content** in the ratios and quarterly tabs:
- Wrap the existing key ratios JSX in `{activeTab === 'ratios' && (...)}` 
- Wrap the existing quarterly table in `{activeTab === 'quarterly' && (...)}`

**Add valuation tab content**:
```tsx
{activeTab === 'valuation' && (
  <div className="flex flex-col gap-2">
    {/* Controls */}
    <div className="flex items-center gap-2 text-[10px] text-white/40">
      <span>WACC</span>
      <select
        value={wacc}
        onChange={(e) => setWacc(parseFloat(e.target.value))}
        className="bg-white/5 border border-white/10 rounded px-1 py-0.5 text-white/70 text-[10px]"
      >
        {[0.10, 0.11, 0.12, 0.13, 0.14, 0.15].map(v => (
          <option key={v} value={v}>{(v*100).toFixed(0)}%</option>
        ))}
      </select>
      <span>Terminal g</span>
      <select
        value={terminalGrowth}
        onChange={(e) => setTerminalGrowth(parseFloat(e.target.value))}
        className="bg-white/5 border border-white/10 rounded px-1 py-0.5 text-white/70 text-[10px]"
      >
        {[0.03, 0.04, 0.05, 0.06, 0.07].map(v => (
          <option key={v} value={v}>{(v*100).toFixed(0)}%</option>
        ))}
      </select>
    </div>

    {/* Models table */}
    {valuationLoading ? (
      <div className="text-white/30 text-[11px]">Loading valuation models...</div>
    ) : valuationData ? (
      <>
        <div className="text-[10px] text-white/30">CMP: ₹{valuationData.cmp?.toLocaleString('en-IN')}</div>
        <table className="w-full text-[11px]">
          <thead>
            <tr className="text-white/30 text-left">
              <th className="pb-1">Model</th>
              <th className="pb-1 text-right">Fair Value</th>
              <th className="pb-1 text-right">vs CMP</th>
              <th className="pb-1 text-right">Signal</th>
            </tr>
          </thead>
          <tbody>
            {[
              { label: 'Graham Number', value: valuationData.graham_number, upside: valuationData.graham_upside_pct },
              { label: 'DCF (10Y)', value: valuationData.dcf_value, upside: valuationData.dcf_upside_pct },
              { label: 'DDM', value: valuationData.ddm_value, upside: valuationData.ddm_upside_pct },
              { label: 'EV/EBITDA (12x)', value: valuationData.ev_ebitda_value, upside: valuationData.ev_ebitda_upside_pct },
              { label: 'PEG Fair Value', value: valuationData.peg_value, upside: valuationData.peg_upside_pct },
            ].map((row) => {
              const signal = row.upside === null ? null : row.upside > 15 ? 'UNDERVALUED' : row.upside < -15 ? 'OVERVALUED' : 'FAIR';
              const signalColor = signal === 'UNDERVALUED' ? 'text-green-400' : signal === 'OVERVALUED' ? 'text-red-400' : 'text-yellow-400';
              return (
                <tr key={row.label} className="border-t border-white/5">
                  <td className="py-1 text-white/60">{row.label}</td>
                  <td className="py-1 text-right text-white/80">
                    {row.value !== null ? `₹${row.value.toLocaleString('en-IN')}` : '—'}
                  </td>
                  <td className={cn('py-1 text-right', row.upside !== null ? (row.upside > 0 ? 'text-green-400' : 'text-red-400') : 'text-white/30')}>
                    {row.upside !== null ? `${row.upside > 0 ? '+' : ''}${row.upside.toFixed(1)}%` : '—'}
                  </td>
                  <td className={cn('py-1 text-right font-medium', signalColor)}>
                    {signal ?? '—'}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>

        {/* DCF assumptions footnote */}
        {valuationData.dcf_assumptions && (
          <div className="text-[9px] text-white/25 mt-1 border-t border-white/5 pt-1">
            DCF: Stage1 {valuationData.dcf_assumptions.stage1_growth_pct}% →
            Stage2 {valuationData.dcf_assumptions.stage2_growth_pct}% →
            Terminal {valuationData.dcf_assumptions.terminal_growth_pct}% |
            WACC {valuationData.dcf_assumptions.wacc_pct}%
            {valuationData.dcf_assumptions.base_fcf_cr !== null &&
              ` | Base FCF ₹${valuationData.dcf_assumptions.base_fcf_cr.toFixed(0)}Cr`}
          </div>
        )}
      </>
    ) : (
      <div className="text-white/30 text-[11px]">No valuation data available</div>
    )}
  </div>
)}
```

---

## Feature 3: Portfolio Optimizer Widget

### Files to create

- `backend/app/routers/portfolio.py` — new file
- `src/components/widgets/PortfolioWidget.tsx` — new file

### Files to modify

- `backend/app/routers/__init__.py`
- `backend/main.py`
- `backend/pyproject.toml` — add `pyportfolioopt` and confirm `yfinance`
- `src/store/terminalStore.ts` — add `PORTFOLIO` command

### Step 1 — Backend: Install `pyportfolioopt`

```bash
cd backend && source .venv/bin/activate && pip install pyportfolioopt
```

Add to `backend/pyproject.toml` under `[project] dependencies`:
```toml
"PyPortfolioOpt>=1.5.5",
"yfinance>=0.2.0",
```

### Step 2 — Backend: Create `backend/app/routers/portfolio.py`

```python
"""Portfolio optimization router.

Uses PyPortfolioOpt for mean-variance and hierarchical risk parity optimization.
Historical price data fetched from Yahoo Finance via yfinance (.NS suffix for NSE).
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/portfolio", tags=["portfolio"])

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

_cache: dict[str, tuple[float, object]] = {}
_CACHE_TTL = 900  # 15 minutes


def _cache_get(key: str):
    entry = _cache.get(key)
    if entry and (time.time() - entry[0]) < _CACHE_TTL:
        return entry[1]
    return None


def _cache_set(key: str, value) -> None:
    _cache[key] = (time.time(), value)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class PortfolioOptimizeRequest(BaseModel):
    symbols: list[str] = Field(..., min_length=3, max_length=30, description="NSE symbols (no .NS suffix needed)")
    period: str = Field(default="2y", description="Lookback period: '1y', '2y', '3y'")
    objective: str = Field(default="max_sharpe", description="'max_sharpe' | 'min_volatility' | 'risk_parity'")
    risk_free_rate: float = Field(default=0.065, ge=0.0, le=0.15, description="Risk-free rate (decimal), default approx RBI repo rate")


class IndividualStats(BaseModel):
    annual_return: float
    annual_volatility: float
    sharpe: float


class PortfolioOptimizeResult(BaseModel):
    weights: dict[str, float]
    expected_annual_return: float
    expected_annual_volatility: float
    sharpe_ratio: float
    correlation_matrix: dict[str, dict[str, float]]
    individual_stats: dict[str, IndividualStats]
    period_used: str
    objective_used: str
    symbols_used: list[str]
    symbols_failed: list[str]
    computed_at: str


class WatchlistPreviewItem(BaseModel):
    symbol: str
    annual_return_1y: float | None
    annual_volatility_1y: float | None
    current_price: float | None


# ---------------------------------------------------------------------------
# Core computation (sync — run in thread pool)
# ---------------------------------------------------------------------------


def _fetch_prices_sync(symbols: list[str], period: str) -> pd.DataFrame:
    """Fetch adjusted close prices for NSE symbols. Returns DataFrame indexed by date."""
    import yfinance as yf
    ns_symbols = [s + ".NS" for s in symbols]
    # auto_adjust=True returns adjusted close as 'Close'
    data = yf.download(ns_symbols, period=period, auto_adjust=True, progress=False)
    if data.empty:
        raise ValueError("yfinance returned empty data")
    # Extract 'Close' prices
    if isinstance(data.columns, pd.MultiIndex):
        prices = data["Close"]
    else:
        prices = data[["Close"]]
    # Rename columns back to bare symbols (strip .NS)
    prices.columns = [c.replace(".NS", "") for c in prices.columns]
    return prices.dropna(how="all")


def _run_optimization_sync(request: PortfolioOptimizeRequest) -> PortfolioOptimizeResult:
    from pypfopt import expected_returns, risk_models, EfficientFrontier, HRPOpt

    symbols = [s.upper() for s in request.symbols]
    prices = _fetch_prices_sync(symbols, request.period)

    # Drop symbols where all prices are NaN (not found)
    valid_cols = [c for c in prices.columns if prices[c].notna().sum() > 10]
    failed = [s for s in symbols if s not in valid_cols]
    prices = prices[valid_cols].dropna()

    if len(valid_cols) < 2:
        raise ValueError(f"Insufficient valid symbols ({len(valid_cols)}). Failed: {failed}")

    # Per-symbol stats
    daily_returns = prices.pct_change().dropna()
    individual_stats: dict[str, IndividualStats] = {}
    for sym in valid_cols:
        dr = daily_returns[sym].dropna()
        ann_ret = float((1 + dr.mean()) ** 252 - 1)
        ann_vol = float(dr.std() * np.sqrt(252))
        sharpe = (ann_ret - request.risk_free_rate) / ann_vol if ann_vol > 0 else 0.0
        individual_stats[sym] = IndividualStats(
            annual_return=round(ann_ret, 4),
            annual_volatility=round(ann_vol, 4),
            sharpe=round(sharpe, 3),
        )

    # Correlation matrix
    corr = daily_returns.corr()
    corr_dict: dict[str, dict[str, float]] = {
        sym: {sym2: round(float(corr.loc[sym, sym2]), 3) for sym2 in valid_cols}
        for sym in valid_cols
    }

    # Optimization
    mu = expected_returns.mean_historical_return(prices)
    S = risk_models.sample_cov(prices)

    weights: dict[str, float] = {}
    exp_ret = 0.0
    exp_vol = 0.0
    sharpe_r = 0.0

    if request.objective == "risk_parity":
        hrp = HRPOpt(daily_returns)
        hrp.optimize()
        raw_weights = hrp.clean_weights()
        weights = {k: round(float(v), 4) for k, v in raw_weights.items() if v > 0.001}
        # Compute portfolio stats from weights
        w = np.array([weights.get(s, 0) for s in valid_cols])
        port_ret = float(mu.values @ w)
        port_vol = float(np.sqrt(w @ S.values @ w))
        exp_ret = round(port_ret, 4)
        exp_vol = round(port_vol, 4)
        sharpe_r = round((exp_ret - request.risk_free_rate) / exp_vol if exp_vol > 0 else 0, 3)
    else:
        ef = EfficientFrontier(mu, S, weight_bounds=(0, 1))
        if request.objective == "max_sharpe":
            ef.max_sharpe(risk_free_rate=request.risk_free_rate)
        else:  # min_volatility
            ef.min_volatility()

        raw_weights = ef.clean_weights()
        weights = {k: round(float(v), 4) for k, v in raw_weights.items() if v > 0.001}
        perf = ef.portfolio_performance(risk_free_rate=request.risk_free_rate)
        exp_ret = round(float(perf[0]), 4)
        exp_vol = round(float(perf[1]), 4)
        sharpe_r = round(float(perf[2]), 3)

    return PortfolioOptimizeResult(
        weights=weights,
        expected_annual_return=exp_ret,
        expected_annual_volatility=exp_vol,
        sharpe_ratio=sharpe_r,
        correlation_matrix=corr_dict,
        individual_stats=individual_stats,
        period_used=request.period,
        objective_used=request.objective,
        symbols_used=valid_cols,
        symbols_failed=failed,
        computed_at=datetime.now(timezone.utc).isoformat(),
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/optimize", response_model=PortfolioOptimizeResult)
async def optimize_portfolio(request: PortfolioOptimizeRequest) -> PortfolioOptimizeResult:
    """Run portfolio optimization on a list of NSE symbols."""
    symbols_key = ",".join(sorted(s.upper() for s in request.symbols))
    cache_key = f"{symbols_key}:{request.period}:{request.objective}:{request.risk_free_rate}"

    cached = _cache_get(cache_key)
    if cached:
        return cached  # type: ignore

    try:
        result = await asyncio.to_thread(_run_optimization_sync, request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.exception("Portfolio optimization failed")
        raise HTTPException(status_code=502, detail=f"Optimization failed: {exc}")

    _cache_set(cache_key, result)
    return result


@router.get("/watchlist-preview", response_model=list[WatchlistPreviewItem])
async def watchlist_preview(symbols: str) -> list[WatchlistPreviewItem]:
    """Quick 1Y stats for a comma-separated list of NSE symbols (for the selection UI).
    
    Usage: GET /portfolio/watchlist-preview?symbols=RELIANCE,TCS,HDFCBANK
    """
    symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not symbol_list:
        raise HTTPException(status_code=422, detail="No symbols provided")

    cache_key = "preview:" + ",".join(sorted(symbol_list))
    cached = _cache_get(cache_key)
    if cached:
        return cached  # type: ignore

    def _fetch():
        import yfinance as yf
        ns_syms = [s + ".NS" for s in symbol_list]
        data = yf.download(ns_syms, period="1y", auto_adjust=True, progress=False)
        if data.empty:
            return []
        if isinstance(data.columns, pd.MultiIndex):
            prices = data["Close"]
        else:
            prices = data[["Close"]]
        prices.columns = [c.replace(".NS", "") for c in prices.columns]

        results = []
        for sym in symbol_list:
            if sym not in prices.columns:
                results.append(WatchlistPreviewItem(symbol=sym, annual_return_1y=None, annual_volatility_1y=None, current_price=None))
                continue
            s = prices[sym].dropna()
            if len(s) < 5:
                results.append(WatchlistPreviewItem(symbol=sym, annual_return_1y=None, annual_volatility_1y=None, current_price=None))
                continue
            dr = s.pct_change().dropna()
            ann_ret = float((1 + dr.mean()) ** 252 - 1)
            ann_vol = float(dr.std() * np.sqrt(252))
            results.append(WatchlistPreviewItem(
                symbol=sym,
                annual_return_1y=round(ann_ret * 100, 2),
                annual_volatility_1y=round(ann_vol * 100, 2),
                current_price=round(float(s.iloc[-1]), 2),
            ))
        return results

    try:
        result = await asyncio.to_thread(_fetch)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    _cache_set(cache_key, result)
    return result
```

### Step 3 — Backend: Register portfolio router

**`backend/app/routers/__init__.py`**: Add import and `__all__` entry same as valuation step.

**`backend/main.py`**: Add `portfolio_router` import and `app.include_router(portfolio_router, prefix="/api")`.

### Step 4 — Frontend: Create `src/components/widgets/PortfolioWidget.tsx`

The file must start with `'use client';`. Full structure:

```typescript
'use client';

import React, { useState, useMemo } from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import { cn } from '@/lib/utils';

// ─── Types ────────────────────────────────────────────────────────────────────

interface WatchlistItem {
  id: number;
  symbol: string;
  exchange: string;
}

interface IndividualStats {
  annual_return: number;
  annual_volatility: number;
  sharpe: number;
}

interface OptimizeResult {
  weights: Record<string, number>;
  expected_annual_return: number;
  expected_annual_volatility: number;
  sharpe_ratio: number;
  correlation_matrix: Record<string, Record<string, number>>;
  individual_stats: Record<string, IndividualStats>;
  period_used: string;
  objective_used: string;
  symbols_used: string[];
  symbols_failed: string[];
  computed_at: string;
}

interface WatchlistPreviewItem {
  symbol: string;
  annual_return_1y: number | null;
  annual_volatility_1y: number | null;
  current_price: number | null;
}
```

**Main component logic**:
1. Load watchlist symbols via `useQuery` from `/api/watchlist` (existing endpoint)
2. State: `selectedSymbols: Set<string>`, `period: '1y'|'2y'|'3y'`, `objective: 'max_sharpe'|'min_volatility'|'risk_parity'`
3. Load preview stats via `useQuery` (enabled when symbols loaded): `GET /api/py/portfolio/watchlist-preview?symbols=SYM1,SYM2,...`
4. Optimize via `useMutation`: `POST /api/py/portfolio/optimize`

**Layout**:
- Left panel (fixed ~180px wide): symbol checklist with 1Y return/vol preview stats, period selector, objective selector, Optimize button
- Right panel (flex): results — weight bars, portfolio stats, correlation heatmap

**Weight visualization** (pure CSS, no charting library):
```tsx
{Object.entries(result.weights)
  .sort(([,a],[,b]) => b - a)
  .map(([sym, w]) => (
    <div key={sym} className="flex items-center gap-2 text-[11px]">
      <span className="w-16 text-white/60 text-right">{sym}</span>
      <div className="flex-1 bg-white/5 rounded-full h-2">
        <div
          className="bg-blue-400 h-2 rounded-full"
          style={{ width: `${(w * 100).toFixed(1)}%` }}
        />
      </div>
      <span className="w-10 text-white/80">{(w * 100).toFixed(1)}%</span>
    </div>
  ))
}
```

**Correlation heatmap** (pure CSS grid):
```tsx
// Color: negative correlation → green, zero → gray, positive → red
// Formula: hue = correlation < 0 ? 120 (green) : 0 (red), saturation = abs(correlation) * 80%
function corrColor(val: number): string {
  if (val === 1) return '#1e3a5f';
  const abs = Math.abs(val);
  const hue = val < 0 ? 120 : 0;
  return `hsl(${hue}, ${Math.round(abs * 70)}%, ${Math.round(20 + (1 - abs) * 15)}%)`;
}
```

### Step 5 — Frontend: Register `PORTFOLIO` command

**In `src/store/terminalStore.ts`**, find where widget commands are defined (look for `'CHART'`, `'WATCH'`, `'MOVERS'` etc.) and add `'PORTFOLIO'` to the appropriate type/union and any command palette registry.

You'll need to also register the widget in the Panel component (`src/components/Panel.tsx` or similar) where commands map to widget components — find the switch/map statement and add:
```typescript
case 'PORTFOLIO':
  return <PortfolioWidget />;
```

---

## Final Checklist Before Marking Complete

- [ ] **Feature 1**: `POST /api/py/ai/chat` accepts `persona` field without error
- [ ] **Feature 1**: Selecting a persona in AiWidget changes system prompt behavior (test: select "Value Analyst", ask "analyse this stock")
- [ ] **Feature 2**: `GET /api/py/valuation/RELIANCE` returns 200 with all 5 models (some may be null — that's OK)
- [ ] **Feature 2**: Valuation tab appears in FundamentalsWidget and shows model table
- [ ] **Feature 2**: Changing WACC dropdown triggers re-fetch with new param
- [ ] **Feature 3**: `pyportfolioopt` installed in backend venv
- [ ] **Feature 3**: `POST /api/py/portfolio/optimize` returns weights for 3+ NSE symbols
- [ ] **Feature 3**: PortfolioWidget loads and renders with watchlist symbols pre-populated
- [ ] **Feature 3**: Optimize button triggers mutation and shows results
- [ ] **Build**: `npm run build` passes with no TypeScript errors
- [ ] **Tests**: `cd backend && pytest -m "not slow"` passes

---

## Common Pitfalls

1. **yfinance rate limiting**: If many symbols are fetched in quick succession, Yahoo Finance may return empty data. The 15-30 minute caches mitigate this. For portfolio preview, batch all symbols in a single `yf.download()` call — never call `yf.Ticker()` in a loop.

2. **PyPortfolioOpt with highly correlated stocks**: If all input stocks are highly correlated (e.g. all PSU banks), the optimizer may produce degenerate weights (100% in one stock). This is mathematically correct — the frontend should display this without crashing.

3. **NSE symbol .NS suffix**: yfinance requires `.NS` suffix for NSE stocks. Add it in the backend; frontend always passes bare symbols (e.g. `RELIANCE`, not `RELIANCE.NS`).

4. **Tab state reset**: When `activeSymbolAtom` changes in FundamentalsWidget, the valuation tab should remain active but re-fetch for the new symbol. The `queryKey: ['valuation', symbol, wacc, terminalGrowth]` handles this automatically via React Query.

5. **Persona system prompt placement**: In the `ai_chat_service.py` agentic loop, the system message must be the **first message** in the array sent to the LLM. Check if there's already a system message prepended somewhere in the existing code — don't double-prepend.

6. **Router registration**: If a router is added to `__init__.py` but not `main.py` (or vice versa), FastAPI will silently fail to register routes. Always update both files.

7. **`asyncio.to_thread` for yfinance**: yfinance and PyPortfolioOpt are **synchronous** libraries. Always wrap them in `await asyncio.to_thread(fn, args...)` inside async route handlers to avoid blocking the event loop.

8. **FundamentalsWidget tab state**: The existing component has no tabs. You're adding tab state. Make sure the `useQuery` calls for screener and morningstar data are NOT conditional on the tab — they should still fetch in the background so switching to "Ratios" is instant. Only the valuation query should be `enabled: !!symbol && activeTab === 'valuation'` since it's a slow yfinance call.
