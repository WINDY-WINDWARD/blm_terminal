"""AI Chat Service — dual-format agentic loop via OpenCode Go.

Two wire formats are supported:
  - OpenAI /chat/completions  — Kimi, Qwen, and other Go models
  - Anthropic /messages       — MiniMax M2.5 and M2.7 on Go

Both loops yield the same SSE-compatible JSON strings so the router and
frontend are completely format-agnostic.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

import asyncio
import httpx

from app.config import settings
from app.services.antigravity_auth import get_antigravity_token

logger = logging.getLogger(__name__)

# Module-level shared httpx client (audit win #10: pool HTTP connections).
# Recreated per event loop so tests / server reloads don't reuse a closed client.
_SHARED_CLIENT_TIMEOUT = 120.0
_shared_client: httpx.AsyncClient | None = None
_shared_client_loop: asyncio.AbstractEventLoop | None = None


def _get_shared_client() -> httpx.AsyncClient:
    """Return the module-level shared httpx.AsyncClient for the current event loop.

    Lazy-initialized on first call; rebuilt when the running event loop changes
    (e.g. FastAPI reload, pytest-asyncio new loop per test). Safe to call from
    sync code — returns the cached client when no loop is running.
    """
    global _shared_client, _shared_client_loop
    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        if _shared_client is None:
            _shared_client = httpx.AsyncClient(timeout=_SHARED_CLIENT_TIMEOUT)
        return _shared_client
    if _shared_client is None or _shared_client_loop is not current_loop:
        _shared_client = httpx.AsyncClient(timeout=_SHARED_CLIENT_TIMEOUT)
        _shared_client_loop = current_loop
    return _shared_client

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_ITER = 10

# Models that use the Anthropic /messages endpoint on Go
ANTHROPIC_MODELS: frozenset[str] = frozenset({"minimax-m2.5", "minimax-m2.7"})

AVAILABLE_MODELS = [
    {"id": "kimi-k2.5",     "label": "Kimi K2.5 (recommended)"},
    {"id": "kimi-k2.6",     "label": "Kimi K2.6 (latest)"},
    {"id": "qwen3.5-plus",  "label": "Qwen3.5 Plus (fast)"},
    {"id": "qwen3.6-plus",  "label": "Qwen3.6 Plus"},
    {"id": "minimax-m2.5",  "label": "MiniMax M2.5"},
    {"id": "minimax-m2.7",  "label": "MiniMax M2.7 (best quality)"},
]

# ---------------------------------------------------------------------------
# Analyst persona system prompts
# ---------------------------------------------------------------------------

PERSONA_SYSTEM_PROMPTS: dict[str, str] = {
    "value": """You are a disciplined value investor analyst in the tradition of Benjamin Graham and Warren Buffett, specialising in NSE-listed Indian equities.

Your analysis framework:
1. QUALITY CHECK: Assess ROCE (>15% is good), ROE (>15% is good), Debt-to-Equity (<1 is preferred), operating cash flow vs net profit consistency. Use company_fdm and get_symbol_data tools.
2. MOAT ASSESSMENT: Does the company have pricing power, switching costs, network effects, or cost advantages? Use sector/industry context from list_sectors and get_industry_stocks.
3. INTRINSIC VALUE: Calculate Graham Number (√(22.5 × EPS × Book Value)). Compare to current price. Assess margin of safety.
4. MANAGEMENT: Check promoter holding %, pledge %, insider transactions via screener_trades.
5. GROWTH CONTEXT: 5-year revenue and profit CAGR, Piotroski F-Score.
6. RED FLAGS: Declining ROCE, rising debt, promoter pledging >20%, frequent equity dilution, poor cash conversion.
7. PORTFOLIO CONSTRUCTION: When asked to build a value portfolio, select 8–15 stocks with strong quality scores (ROCE >15%, ROE >15%, D/E <1), then use `optimize_portfolio(objective='max_sharpe')` to find the optimal weight distribution. Save the result with `create_watchlist` and `bulk_replace_watchlist`.

Always cite the specific data you retrieved. State your conclusion: BUY / HOLD / AVOID with clear reasoning. Be intellectually honest — if data is insufficient, say so. Do not confuse activity with productivity.""",

    "earnings": """You are a forensic earnings analyst specialising in NSE-listed Indian companies.

Your analysis framework:
1. HEADLINE NUMBERS: Revenue QoQ and YoY growth, Net Profit QoQ and YoY growth, EPS trend. Use company_fdm for quarterly data.
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
6. PORTFOLIO CONSTRUCTION: Translate sector rotation views into concrete portfolios. Use `list_sectors` and `get_sector_stocks` to identify top-ranked stocks per sector, then use `optimize_portfolio(objective='risk_parity')` for a balanced sector-rotated portfolio. Save with `create_watchlist` and `bulk_replace_watchlist`.

Use get_global_news with threat_level filters to identify macro risks. Be explicit about the difference between short-term (1-3 months) and medium-term (6-12 months) views.""",
}


def _get_system_prompt(symbol: str, exchange: str, persona: str | None, mode: str | None = None) -> str:
    """Build the system prompt, optionally prepending a persona definition
    and/or appending the Script Lab instructions."""
    if persona and persona in PERSONA_SYSTEM_PROMPTS:
        base = PERSONA_SYSTEM_PROMPTS[persona] + f"\n\nCurrent symbol context: {symbol} on {exchange}."
    else:
        # No persona — fall back to the rich default system prompt
        base = _build_system_prompt(symbol, exchange)
    if (mode or "research") == "script":
        base += "\n\n" + SCRIPT_LAB_PROMPT
    return base


# ---------------------------------------------------------------------------
# Tool description registry — sourced from mcp_server.py docstrings
# ---------------------------------------------------------------------------
# This ensures the AI agent's tool descriptions stay in sync with the MCP
# tool definitions automatically. Edit the docstring in mcp_server.py and
# the change propagates here at import time — no duplication needed.

def _mcp_tool_docs() -> dict[str, str]:
    """Return {tool_name: docstring} for every @mcp.tool() function in mcp_server."""
    from app import mcp_server  # local import to avoid circular deps at module level

    docs: dict[str, str] = {}
    for name, obj in inspect.getmembers(mcp_server, inspect.isfunction):
        doc = inspect.getdoc(obj)
        if doc:
            docs[name] = doc
    return docs


_TOOL_DOCS: dict[str, str] = _mcp_tool_docs()


def _desc(tool_name: str, fallback: str = "") -> str:
    """Look up the MCP docstring for a tool, falling back to a literal string."""
    return _TOOL_DOCS.get(tool_name, fallback)


# ---------------------------------------------------------------------------
# Tool definitions — OpenAI /chat/completions format
# ---------------------------------------------------------------------------

BLM_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "health_check",
            "description": _desc("health_check"),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_top_gainers",
            "description": _desc("get_top_gainers"),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_top_losers",
            "description": _desc("get_top_losers"),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_bulk_deals",
            "description": _desc("get_bulk_deals"),
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Single NSE symbol. Mutually exclusive with symbols."},
                    "symbols": {"type": "array", "items": {"type": "string"}, "description": "Multiple NSE symbols. Mutually exclusive with symbol."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_block_deals",
            "description": _desc("get_block_deals"),
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Single NSE symbol. Mutually exclusive with symbols."},
                    "symbols": {"type": "array", "items": {"type": "string"}, "description": "Multiple NSE symbols. Mutually exclusive with symbol."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_largedeal_snapshot",
            "description": _desc("get_largedeal_snapshot"),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_change_ranges",
            "description": _desc("get_change_ranges"),
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Single NSE symbol. Mutually exclusive with symbols."},
                    "symbols": {"type": "array", "items": {"type": "string"}, "description": "Multiple NSE symbols. Mutually exclusive with symbol."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_symbol_data",
            "description": _desc("get_symbol_data"),
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Single NSE symbol. Mutually exclusive with symbols."},
                    "symbols": {"type": "array", "items": {"type": "string"}, "description": "Multiple NSE symbols. Mutually exclusive with symbol."},
                    "fields": {"type": "array", "items": {"type": "string"}, "description": "Optional: limit response to only these field names."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_52week_low_stocks",
            "description": _desc("get_52week_low_stocks"),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_52week_high_stocks",
            "description": _desc("get_52week_high_stocks"),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_volume_gainers",
            "description": _desc("get_volume_gainers"),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "screener_search",
            "description": _desc("screener_search"),
            "parameters": {
                "type": "object",
                "properties": {
                    "q": {"type": "string", "description": "Company name or symbol fragment, e.g. 'HDFC' or 'Tata Steel'."},
                },
                "required": ["q"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "company_fdm",
            "description": _desc("company_fdm"),
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Single NSE symbol."},
                    "sections": {"type": "array", "items": {"type": "string"}, "description": "List of data sections to return. Valid options: screener, tradingview, morningstar, valuation, nse_ratios, corporate"},
                    "consolidated": {"type": "boolean", "description": "Use consolidated financials for Screener data (default true)."},
                },
                "required": ["symbol"]
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "screener_trades",
            "description": _desc("screener_trades"),
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Single NSE symbol. Mutually exclusive with symbols."},
                    "symbols": {"type": "array", "items": {"type": "string"}, "description": "Multiple NSE symbols. Mutually exclusive with symbol."},
                    "consolidated": {"type": "boolean", "description": "Use consolidated financials (default true)."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_tql_screener",
            "description": (
                "Run a custom TQL (Ticker Query Language) screener query against all NSE stocks "
                "and return matching symbols with their data. Use this to find stocks meeting "
                "specific technical or fundamental criteria.\n\n"
                "SUPPORTED FIELDS:\n"
                "  Technical indicators (support interval prefix like '1h:RSI', 'W:ATR'):\n"
                "    RSI            — Relative Strength Index (0–100)\n"
                "    ATR            — Average True Range\n"
                "    MACD           — MACD line value\n"
                "    MACDSignal     — MACD signal line value\n"
                "    MACDHist       — MACD histogram value\n"
                "    BBWidth        — Bollinger Band width\n"
                "    BBSqueeze      — Boolean: true when bands are squeezed\n"
                "    HV20           — 20-day historical volatility\n"
                "    HV60           — 60-day historical volatility\n"
                "    Sharpe60       — 60-day Sharpe ratio\n"
                "    Sharpe126      — 126-day Sharpe ratio\n"
                "  Price & volume:\n"
                "    Change         — Intraday % change\n"
                "    Volume         — Today's trading volume\n"
                "    Close          — Last close price\n"
                "    DataPoints     — Number of data points available\n"
                "  Fundamentals:\n"
                "    PE             — Price-to-Earnings ratio\n"
                "    MomentumScore  — Composite momentum score\n"
                "  Returns (period-based):\n"
                "    Return1w, Return1m, Return3m, Return6m, Return1y\n"
                "  52-week position:\n"
                "    From52wHigh    — % below 52-week high (negative = below)\n"
                "    From52wLow     — % above 52-week low\n"
                "  Classification:\n"
                "    Sector         — e.g. 'Banks', 'IT', 'Pharma' (use = or IN)\n"
                "    Industry       — e.g. 'Bank - Private', 'IT Services' (use = or IN)\n"
                "    Symbol         — NSE symbol string\n\n"
                "INTERVAL PREFIXES (for technical indicators only):\n"
                "  No prefix → uses default_interval (default: 1d)\n"
                "  1h:RSI, W:ATR, M:MACD, 1d:BBWidth\n"
                "  Valid intervals: 1d, 1h, W, M\n\n"
                "OPERATORS: >, <, >=, <=, =, !=, IN (...), AND, OR, NOT, ( )\n\n"
                "EXAMPLES:\n"
                '  RSI > 60 AND Sector = "Banks"\n'
                '  PE < 20 AND Return1y > 20 AND MomentumScore > 50\n'
                '  1h:RSI < 30 AND Volume > 500000\n'
                '  From52wHigh > -10 AND MomentumScore > 70\n'
                '  Sector IN ("Banks", "Finance") AND RSI > 50 AND PE < 25'
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tql": {
                        "type": "string",
                        "description": 'TQL query expression, e.g. RSI > 60 AND Sector = "Banks" AND PE < 20',
                    },
                    "default_interval": {
                        "type": "string",
                        "description": "Default interval for un-prefixed indicator fields: 1d (default), 1h, W, M",
                    },
                    "sort_by": {
                        "type": "string",
                        "description": "Field name to sort results by (default: symbol)",
                    },
                    "order": {
                        "type": "string",
                        "description": "Sort direction: asc (default) or desc",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results to return, 1–200 (default: 50)",
                    },
                },
                "required": ["tql"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_stock_universe",
            "description": _desc("list_stock_universe"),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_stock_universe",
            "description": _desc("get_stock_universe"),
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Single NSE symbol. Mutually exclusive with symbols."},
                    "symbols": {"type": "array", "items": {"type": "string"}, "description": "Multiple NSE symbols. Mutually exclusive with symbol."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_stock_universe",
            "description": _desc("search_stock_universe"),
            "parameters": {
                "type": "object",
                "properties": {
                    "prefix": {"type": "string", "description": "Leading characters of symbol or company name, e.g. 'HDFC' or 'Tata'."},
                },
                "required": ["prefix"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_watchlist",
            "description": _desc("list_watchlist"),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_watchlists",
            "description": _desc("list_watchlists"),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_watchlist_items",
            "description": _desc("get_watchlist_items"),
            "parameters": {
                "type": "object",
                "properties": {
                    "watchlist_id": {"type": "integer", "description": "Numeric watchlist ID from list_watchlists()."},
                },
                "required": ["watchlist_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_watchlist_symbols",
            "description": "Fetch distinct symbols from the default watchlist as a flat list.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_watchlist_item",
            "description": "Delete a watchlist item from the default watchlist by its numeric ID. Returns {ok: true} on success.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_id": {"type": "integer", "description": "Numeric ID of the watchlist item to remove."},
                },
                "required": ["item_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "optimize_portfolio",
            "description": "Run portfolio optimization on a list of NSE symbols. Supports mean-variance (max_sharpe, min_volatility) and hierarchical risk parity (risk_parity). Returns weights, expected return/volatility/Sharpe, correlation matrix, and per-symbol stats.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbols": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of NSE ticker symbols (no .NS suffix). Requires 3–30 symbols.",
                    },
                    "period": {
                        "type": "string",
                        "enum": ["1y", "2y", "3y"],
                        "description": "Lookback period: '1y', '2y' (default), or '3y'.",
                    },
                    "objective": {
                        "type": "string",
                        "enum": ["max_sharpe", "min_volatility", "risk_parity"],
                        "description": "Optimization goal: 'max_sharpe' (default), 'min_volatility', or 'risk_parity'.",
                    },
                    "risk_free_rate": {
                        "type": "number",
                        "description": "Annual risk-free rate as decimal (default 0.065 ≈ RBI repo rate).",
                    },
                },
                "required": ["symbols"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_watchlist",
            "description": "Create a new named watchlist. Returns the created watchlist with its id and creation timestamp.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Watchlist name — alphanumeric and hyphens only (e.g. 'Tech-Buys', 'Portfolio-2024')."},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_watchlist_item",
            "description": "Add a single symbol/exchange pair to a named watchlist. Idempotent — returns the existing row if already present.",
            "parameters": {
                "type": "object",
                "properties": {
                    "watchlist_id": {"type": "integer", "description": "Numeric watchlist ID — use list_watchlists() to enumerate valid IDs."},
                    "symbol": {"type": "string", "description": "NSE ticker symbol (e.g. 'RELIANCE', 'TCS')."},
                    "exchange": {"type": "string", "description": "Exchange (default 'NSE')."},
                },
                "required": ["watchlist_id", "symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bulk_replace_watchlist",
            "description": "Atomically replace all items in a watchlist with a new set of symbols. Use this to save an optimized portfolio — it deletes all existing items and inserts the new set in a single transaction.",
            "parameters": {
                "type": "object",
                "properties": {
                    "watchlist_id": {"type": "integer", "description": "Numeric watchlist ID to overwrite."},
                    "symbols": {"type": "array", "items": {"type": "string"}, "description": "List of NSE ticker symbols to set as the new portfolio."},
                    "exchange": {"type": "string", "description": "Exchange for all symbols (default 'NSE')."},
                },
                "required": ["watchlist_id", "symbols"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_notifications",
            "description": _desc("get_notifications"),
            "parameters": {
                "type": "object",
                "properties": {
                    "watchlist_id": {"type": "integer", "description": "Numeric watchlist ID."},
                    "limit": {"type": "integer", "description": "Max notifications to return."},
                    "since_id": {"type": "integer", "description": "Only return notifications with id greater than this."},
                },
                "required": ["watchlist_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_global_notifications",
            "description": _desc("get_global_notifications"),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Max alerts to return."},
                    "trigger_type": {
                        "type": "string",
                        "enum": [
                            "52w_high_breakout", "52w_low_breakout", "volume_breakout",
                            "top_gainer", "top_loser", "results_upcoming",
                            "rsi_oversold", "rsi_overbought", "macd_bullish_cross",
                            "macd_bearish_cross", "bb_squeeze_alert", "bb_upper_break",
                            "bb_lower_break", "volatility_spike", "atr_expansion",
                            "momentum_surge", "return_1w_spike", "streak_up_5d",
                            "streak_down_5d", "near_52w_high", "near_52w_low",
                        ],
                        "description": "Filter by event type. Omit to return all types.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_morningstar_fairvalue",
            "description": _desc("get_morningstar_fairvalue"),
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Single NSE symbol. Mutually exclusive with symbols."},
                    "symbols": {"type": "array", "items": {"type": "string"}, "description": "Multiple NSE symbols. Mutually exclusive with symbol."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_global_news",
            "description": _desc("get_global_news"),
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "Number of days to look back (default 7)."},
                    "limit": {"type": "integer", "description": "Maximum articles to return (default 50)."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_company_news",
            "description": _desc("get_company_news"),
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Single NSE symbol. Mutually exclusive with symbols."},
                    "symbols": {"type": "array", "items": {"type": "string"}, "description": "Multiple NSE symbols. Mutually exclusive with symbol."},
                    "days": {"type": "integer", "description": "Days to look back (default 30)."},
                    "limit": {"type": "integer", "description": "Max articles per symbol (default 50)."},
                    "refresh": {"type": "boolean", "description": "Force a live fetch from upstream (default false)."},
                    "sentiment": {"type": "string", "description": "Filter by sentiment (POSITIVE, NEGATIVE, NEUTRAL)."},
                    "threat_level": {"type": "string", "description": "Filter by threat level (LOW, MEDIUM, HIGH, CRITICAL)."},
                    "language": {"type": "string", "description": "Filter by two-letter language code (en, hi, zh, etc.)."}
                }
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_industries",
            "description": _desc("list_industries"),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_sectors",
            "description": _desc("list_sectors"),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_industry_stocks",
            "description": _desc("get_industry_stocks"),
            "parameters": {
                "type": "object",
                "properties": {
                    "slug": {"type": "string", "description": "Industry slug from list_industries(), e.g. 'bank-private', 'it-services-consulting'."},
                },
                "required": ["slug"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_sector_stocks",
            "description": _desc("get_sector_stocks"),
            "parameters": {
                "type": "object",
                "properties": {
                    "slug": {"type": "string", "description": "Sector slug from list_sectors(), e.g. 'banks', 'finance', 'it-services'."},
                },
                "required": ["slug"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_upcoming_events",
            "description": _desc("get_upcoming_events"),
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "NSE symbol to check for upcoming board meetings, earnings, and corporate events."},
                },
                "required": ["symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_recent_announcements",
            "description": _desc("get_recent_announcements"),
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "NSE symbol to check for recent corporate announcements and past results."},
                },
                "required": ["symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_positions",
            "description": _desc("get_positions"),
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["OPEN", "CLOSED"],
                        "description": "Optional status filter ('OPEN' or 'CLOSED'). Defaults to returning all positions.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_position",
            "description": _desc("open_position"),
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "NSE stock symbol, e.g. 'RELIANCE', 'TCS'."},
                    "quantity": {"type": "integer", "description": "Initial number of shares to buy."},
                    "price": {"type": "number", "description": "Execution buy price per share."},
                    "notes": {"type": "string", "description": "Optional trading strategy or setup notes."},
                },
                "required": ["symbol", "quantity", "price"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_position_leg",
            "description": _desc("add_position_leg"),
            "parameters": {
                "type": "object",
                "properties": {
                    "trade_id": {"type": "integer", "description": "ID of the position to execute the leg on."},
                    "action": {
                        "type": "string",
                        "enum": ["BUY", "SELL"],
                        "description": "Execution action: 'BUY' (adds shares & recalculates avg buy price) or 'SELL' (scales out/realizes P&L).",
                    },
                    "quantity": {"type": "integer", "description": "Number of shares to execute."},
                    "price": {"type": "number", "description": "Execution price per share."},
                    "notes": {"type": "string", "description": "Optional notes for this execution leg."},
                },
                "required": ["trade_id", "action", "quantity", "price"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_position_leg",
            "description": _desc("update_position_leg"),
            "parameters": {
                "type": "object",
                "properties": {
                    "leg_id": {"type": "integer", "description": "ID of the position leg to modify."},
                    "action": {
                        "type": "string",
                        "enum": ["BUY", "SELL"],
                        "description": "Updated action.",
                    },
                    "quantity": {"type": "integer", "description": "Updated number of shares."},
                    "price": {"type": "number", "description": "Updated execution price per share."},
                    "notes": {"type": "string", "description": "Updated notes."},
                },
                "required": ["leg_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_position_leg",
            "description": _desc("delete_position_leg"),
            "parameters": {
                "type": "object",
                "properties": {
                    "leg_id": {"type": "integer", "description": "ID of the execution leg to delete."},
                },
                "required": ["leg_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_position",
            "description": _desc("delete_position"),
            "parameters": {
                "type": "object",
                "properties": {
                    "trade_id": {"type": "integer", "description": "ID of the position to delete."},
                },
                "required": ["trade_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_scripts",
            "description": "List the user's saved chart scripts (id, name, head revision). Builtin examples are included. Call this first when the user refers to an existing script by name.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_script",
            "description": "Fetch a script's head revision manifest and full code plus the list of revision numbers. Always read the current code with this before writing a revision.",
            "parameters": {
                "type": "object",
                "properties": {
                    "script_id": {"type": "integer", "description": "Numeric script ID from list_scripts()."},
                },
                "required": ["script_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "validate_script_code",
            "description": "Schema + static validation for chart-script code (manifest, params, outputs, forbidden syntax). Returns valid/errors plus parsed name/outputs/params. The backend never executes JS. ALWAYS validate new or revised code with this before create_script / revise_script.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Full script source including the // @blm-script JSON header and function calculate(ctx)."},
                },
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_script",
            "description": "Save NEW chart-script code as revision 1 under a unique name. Validate first with validate_script_code. Emits an accept/discard card in the chat UI — the script reaches the chart only if the user accepts it there. Do NOT paste the full code into your chat reply; summarize what it does.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Unique script name, 1-64 chars (e.g. 'RSI Divergence')."},
                    "description": {"type": "string", "description": "One-line plain-language description (max 280 chars)."},
                    "code": {"type": "string", "description": "Full validated script source."},
                    "note": {"type": "string", "description": "Short revision note describing this version (max 280 chars)."},
                },
                "required": ["name", "code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "revise_script",
            "description": "Save a NEW revision of an existing user script (builtins cannot be revised — import a copy concept via create_script instead). Read current code with get_script first, validate with validate_script_code, then revise. Emits an accept/discard card; user acceptance puts it on the chart. Do NOT paste the full code into your chat reply.",
            "parameters": {
                "type": "object",
                "properties": {
                    "script_id": {"type": "integer", "description": "Numeric script ID from list_scripts()."},
                    "code": {"type": "string", "description": "Full validated script source for the new revision."},
                    "note": {"type": "string", "description": "Short note describing what changed (max 280 chars)."},
                },
                "required": ["script_id", "code"],
            },
        },
    },
]

# ---------------------------------------------------------------------------
# Tool definitions — Anthropic /messages format (MiniMax on Go)
# Same tools, different schema shape: input_schema instead of parameters,
# no outer {"type": "function", "function": {...}} wrapper.
# ---------------------------------------------------------------------------

BLM_TOOLS_ANTHROPIC: list[dict[str, Any]] = [
    {
        "name": t["function"]["name"],
        "description": t["function"]["description"],
        "input_schema": t["function"].get("parameters", {"type": "object", "properties": {}, "required": []}),
    }
    for t in BLM_TOOLS
]

# ---------------------------------------------------------------------------
# Tool executor
# ---------------------------------------------------------------------------


async def _execute_tool(name: str, args: dict[str, Any]) -> Any:
    from app.mcp_server import (
        add_watchlist_item,
        bulk_replace_watchlist,
        create_watchlist,
        get_52week_high_stocks,
        get_52week_low_stocks,
        get_block_deals,
        get_bulk_deals,
        get_change_ranges,
        get_company_news,
        get_global_news,
        get_global_notifications,
        get_industry_stocks,
        get_largedeal_snapshot,
        get_morningstar_fairvalue,
        get_notifications,
        get_sector_stocks,
        get_stock_universe,
        get_symbol_data,
        get_top_gainers,
        get_top_losers,
        get_volume_gainers,
        get_watchlist_items,
        get_watchlist_symbols,
        health_check,
        list_industries,
        list_sectors,
        list_stock_universe,
        list_watchlist,
        list_watchlists,
        optimize_portfolio,
        remove_watchlist_item,
        get_positions,
        open_position,
        add_position_leg,
        update_position_leg,
        delete_position_leg,
        delete_position,
        run_tql_screener,
        company_fdm,
        screener_search,
        screener_trades,
        search_stock_universe,
        get_upcoming_events,
        get_recent_announcements,
    )
    from app.services.script_ai_tools import (
        list_scripts,
        get_script,
        validate_script_code,
        create_script,
        revise_script,
    )

    dispatch: dict[str, Any] = {
        "add_watchlist_item": add_watchlist_item,
        "bulk_replace_watchlist": bulk_replace_watchlist,
        "create_watchlist": create_watchlist,
        "get_watchlist_symbols": get_watchlist_symbols,
        "health_check": health_check,
        "get_top_gainers": get_top_gainers,
        "get_top_losers": get_top_losers,
        "get_bulk_deals": get_bulk_deals,
        "get_block_deals": get_block_deals,
        "get_largedeal_snapshot": get_largedeal_snapshot,
        "get_change_ranges": get_change_ranges,
        "get_symbol_data": get_symbol_data,
        "get_52week_low_stocks": get_52week_low_stocks,
        "get_52week_high_stocks": get_52week_high_stocks,
        "get_volume_gainers": get_volume_gainers,
        "screener_search": screener_search,
        "company_fdm": company_fdm,
        "screener_trades": screener_trades,
        "get_upcoming_events": get_upcoming_events,
        "get_recent_announcements": get_recent_announcements,
        "run_tql_screener": run_tql_screener,
        "list_stock_universe": list_stock_universe,
        "get_stock_universe": get_stock_universe,
        "search_stock_universe": search_stock_universe,
        "list_watchlist": list_watchlist,
        "list_watchlists": list_watchlists,
        "get_watchlist_items": get_watchlist_items,
        "get_notifications": get_notifications,
        "get_global_notifications": get_global_notifications,
        "get_morningstar_fairvalue": get_morningstar_fairvalue,
        "get_global_news": get_global_news,
        "get_company_news": get_company_news,
        "list_industries": list_industries,
        "list_sectors": list_sectors,
        "get_industry_stocks": get_industry_stocks,
        "get_sector_stocks": get_sector_stocks,
        "optimize_portfolio": optimize_portfolio,
        "remove_watchlist_item": remove_watchlist_item,
        "get_positions": get_positions,
        "open_position": open_position,
        "add_position_leg": add_position_leg,
        "update_position_leg": update_position_leg,
        "delete_position_leg": delete_position_leg,
        "delete_position": delete_position,
        "list_scripts": list_scripts,
        "get_script": get_script,
        "validate_script_code": validate_script_code,
        "create_script": create_script,
        "revise_script": revise_script,
    }

    fn = dispatch.get(name)
    if fn is None:
        raise ValueError(f"Unknown tool: {name}")
    return await fn(**args)


def _truncate_tool_result(result: Any, max_chars: int = 8000) -> str:
    text = json.dumps(result, default=str)
    if len(text) > max_chars:
        text = text[:max_chars] + f"... [truncated, {len(text) - max_chars} chars omitted]"
    return text


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------


SCRIPT_LAB_PROMPT = """## Script Lab Mode (chart scripts)

The user is asking for a custom chart indicator/overlay. You own the code;
the user owns intent + parameters. There is no user-facing code surface —
never ask the user to write or paste code.

Workflow per request:
1. If the user names an existing script, call `list_scripts` (then
   `get_script` for its code) before writing anything.
2. Write the full script source: a `// @blm-script {...}` single-line JSON
   header followed by a top-level synchronous `function calculate(ctx)`.
3. ALWAYS call `validate_script_code` on the code first. Fix every error it
   returns and re-validate until `valid: true`.
4. Save with `create_script` (new) or `revise_script` (existing user script;
   builtins cannot be revised — recreate the idea via `create_script`).
   This emits an accept/discard card in the chat — the ONLY path to the
   chart. Nothing goes live until the user presses Accept there.
5. Do NOT paste the full code in your reply. Summarize what it plots, its
   parameters, and how to tweak it in plain language (under 500 words total).

Script format (spec v1 — nothing else is accepted):
- Header: `// @blm-script {"name":"...","version":1,"description":"...",
  "params":[...],"outputs":[...],"needs_fundamentals":false}`
- Params (max 24, every key MUST be referenced by the code): int/number
  (`min/max/step` + default), bool, select (`options` >= 2), color (hex),
  source (one of open/high/low/close/hlc3/hl2/ohlc4/volume).
- Outputs (1-8, ids MUST match keys returned by calculate): line
  (`overlay` default true), histogram, markers (`pos` aboveBar|belowBar,
  `shape` arrowUp|arrowDown|circle|square, `text` <= 8 chars), priceline
  (single number), band (`{upper:<lineId>, lower:<lineId>}` naming two line
  outputs of the same script).
- `calculate(ctx)` is pure and synchronous: only `ctx`, frozen `BLM`, and
  `Math`. No imports, fetch, timers, randomness, or DOM. `async`/classes
  are rejected. Return EXACTLY the manifest's output ids; every series
  array MUST have length === `ctx.bars.length` (`number|null` per bar,
  `null` = gap; markers = array per bar, usually empty).
- `ctx.bars`: ascending `{time (sec), o,h,l,c, v}` (volume flat on the live
  edge). `ctx.params`: values by key. `ctx.symbol/exchange/interval`: the
  host chart's (scripts always run on the host chart — never take
  symbol/timeframe as params). `ctx.fundamentals` exists ONLY when
  `needs_fundamentals: true` (quarterly step-filled + pe/roe/roce/
  marketCapCr); Safe-Mode users have no fundamentals — keep scripts
  price-based unless the user explicitly wants fundamentals.
- Stdlib `BLM.*` (same semantics as the terminal's indicator engine, null
  warmup, never throws on short input): `sma(values,period)`,
  `ema(values,period)`, `rsi(closes,period)`, `macd(closes,fast,slow,signal)`
  → `{macdLine,signalLine,hist}`, `bb(closes,period,mult)` →
  `{basis,upper,lower}`, `atr(highs,lows,closes,period)`,
  `stoch(highs,lows,closes,k,slowing,d)` → `{k,d}`, `obv(closes,volumes)`,
  `vwap(highs,lows,closes,volumes)`, `highest/lowest(values,period)`,
  `change(values)`, `nz(value,fallback=0)`.
- Limits: code ≤ 64KB, exec ≤ 2000ms, bars ≤ 2000. Warmup nulls: guard
  `null` before arithmetic or propagate it.
- Revision notes: `note` should say what changed (shown in history).
"""


def _build_system_prompt(symbol: str, exchange: str) -> str:
    return f"""You are BLM Terminal AI — an expert financial research analyst embedded in BLM Terminal, a professional NSE equity research and trading platform.

## Your Role
You help traders and investors cut through large volumes of market data to identify opportunities, assess risks, and make well-informed decisions. You think like a buy-side analyst: rigorous, data-driven, and focused on what actually matters for the investment thesis.

## Active Context
- Active symbol: {symbol} ({exchange})
- When the user refers to "the stock", "this company", or "current symbol", assume {symbol} unless stated otherwise.
- Do NOT re-fetch data already retrieved in this conversation — use it directly.

## Research Approach
- Always pull live data from the tools before drawing conclusions — never answer market data questions from memory.
- For a single stock: fetch fundamentals (company_fdm), price data (get_symbol_data), and deal flow (screener_trades or get_bulk_deals) together when relevant — paint a complete picture.
- For market scans: combine movers, volume, breakout, and sector data to identify themes, not just lists.
- For sector/industry questions: use list_industries or list_sectors first, then drill into specific stocks.
- When comparing stocks: fetch data for all of them in parallel in a single turn.
- Chain tool calls across turns only when later calls depend on earlier results.
- Stop calling tools as soon as you have enough data to answer completely.

## What You Can Help With
- **Fundamental analysis**: P/E, ROCE, ROE, debt, sales/profit growth, earnings trends, fair value vs market price
- **Price & momentum**: LTP, 52-week range, multi-timeframe returns, volume surges, breakout signals
- **Deal flow**: Today's bulk/block deals, historical insider trades, promoter activity patterns
- **Market scanning**: Top gainers/losers, 52-week highs/lows, volume movers, RSI/MACD signals
- **Custom screening**: Use `run_tql_screener` to find stocks by any combination of technical and fundamental criteria — e.g. `RSI > 60 AND Sector = "Banks" AND PE < 20`. Supports RSI, ATR, MACD, BBWidth, BBSqueeze, HV20, HV60, Close, Volume, Change, PE, MomentumScore, Return1w/1m/3m/6m/1y, From52wHigh, From52wLow, Sector, Industry. Prefix indicators with an interval for non-daily timeframes: `1h:RSI`, `W:ATR`, `M:MACD`.
- **Sector rotation**: Industry and sector PE, advance/decline, sentiment, top stocks by market cap
- **News & catalysts**: Company-specific news, earnings announcements, macro events affecting the market
- **Watchlist analysis**: Review held positions, flag signals across watched stocks
- **Portfolio & positions management**: Track, open, and manage portfolio holdings and executions using `get_positions`, `open_position`, `add_position_leg`, `update_position_leg`, `delete_position_leg`, and `delete_position`. Inspect current quantity, average buy price, P/E, realized/unrealized P&L, and technical momentum state across holdings. Execute trade entries and scale-outs as requested by the user.
- **Portfolio optimization**: Build and optimize portfolios using mean-variance (max Sharpe, min volatility) or hierarchical risk parity. Fetch a watchlist's symbols, run `optimize_portfolio`, interpret the weights and risk metrics, and save the result as a new or existing watchlist using `create_watchlist` and `bulk_replace_watchlist`.

## Output Format
- Lead with the key insight or number — not a preamble.
- Use markdown tables for multi-column data (prices, financials, comparisons).
- Format Indian numbers with Indian comma notation (1,23,456) or use Cr/L suffixes for large figures.
- When analyzing a stock, structure your response as: **Price context → Fundamentals → Catalysts/Risks → Verdict**.
- Cite which tools you called at the end of each response in italics (e.g., *Sources: company_fdm, get_symbol_data*).
- If a tool returns an error or no data, acknowledge the gap and work with what you have.

## Constraints
HARD CONSTRAINT: Keep responses under 500 words unless the user explicitly asks for a detailed report or full analysis.
Be an analyst, not a search engine — synthesize and interpret the data, don't just dump it.
"""


# ---------------------------------------------------------------------------
# Shared tool execution helper
# ---------------------------------------------------------------------------


async def _run_tools_parallel(
    tool_calls: list[dict[str, Any]],
    seen_calls: set[str],
    session_id: int | str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Execute tool calls in parallel. Returns (sse_events, tool_result_messages) in OpenAI format."""

    async def _call(tc: dict[str, Any]) -> tuple[str, str, str, str | None]:
        tool_name = tc["name"]
        args = tc["args"]
        raw_args = json.dumps(args)
        call_key = f"{tool_name}:{raw_args}"

        already_seen = call_key in seen_calls
        seen_calls.add(call_key)

        # Script mutations are attributed to this chat session (revision links).
        if (
            tool_name in ("create_script", "revise_script")
            and session_id is not None
            and "chat_session_id" not in args
        ):
            try:
                args = {**args, "chat_session_id": int(session_id)}
            except (TypeError, ValueError):
                pass

        extra_event: str | None = None
        if already_seen:
            content_str = json.dumps({"error": "Duplicate call — data already retrieved. Use it directly."})
        else:
            try:
                result = await asyncio.wait_for(_execute_tool(tool_name, args), timeout=120.0)
                # Script mutations carry a UI card: pop it out of the LLM
                # payload and emit it as its own SSE event (Accept/Discard).
                if tool_name in ("create_script", "revise_script") and isinstance(result, dict):
                    card = result.pop("script_card", None)
                    if isinstance(card, dict):
                        extra_event = json.dumps({"type": "script_card", **card})
                content_str = _truncate_tool_result(result)
            except asyncio.TimeoutError:
                content_str = json.dumps({"error": f"{tool_name} timed out after 120s"})
            except Exception as exc:
                logger.warning("Tool %s failed: %s", tool_name, exc)
                content_str = json.dumps({"error": str(exc)})

        return tool_name, tc["id"], content_str, extra_event

    results = await asyncio.gather(*[_call(tc) for tc in tool_calls])

    sse_events = []
    tool_msgs = []
    for tool_name, tool_id, content_str, extra_event in results:
        preview = content_str[:120] + "..." if len(content_str) > 120 else content_str
        sse_events.append(json.dumps({"type": "tool_result", "name": tool_name, "preview": preview}))
        if extra_event is not None:
            sse_events.append(extra_event)
        tool_msgs.append({"id": tool_id, "name": tool_name, "content": content_str})

    return sse_events, tool_msgs


# ---------------------------------------------------------------------------
# OpenAI loop — Kimi, Qwen, and other /chat/completions models
# ---------------------------------------------------------------------------



from app.services.llm_provider import stream_chat_completion


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def run_chat_agent(
    messages: list[dict[str, Any]],
    symbol: str,
    exchange: str,
    model: str = "kimi-k2.5",
    persona: str | None = None,
    session_id: str | int | None = None,
    mode: str | None = None,
) -> AsyncGenerator[str, None]:
    system_prompt = _get_system_prompt(symbol, exchange, persona, mode)

    seen_calls = set()
    async def executor(tool_calls: list[dict[str, Any]]) -> tuple[list[str], list[dict[str, Any]]]:
        return await _run_tools_parallel(tool_calls, seen_calls, session_id)

    tools = BLM_TOOLS if model not in {"minimax-m2.5", "minimax-m2.7"} else BLM_TOOLS_ANTHROPIC

    async for chunk in stream_chat_completion(
        messages=messages,
        model=model,
        tools=tools,
        tool_executor=executor,
        system_prompt=system_prompt,
        session_id=session_id,
    ):
        yield chunk
