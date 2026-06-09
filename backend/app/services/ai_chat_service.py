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
1. QUALITY CHECK: Assess ROCE (>15% is good), ROE (>15% is good), Debt-to-Equity (<1 is preferred), operating cash flow vs net profit consistency. Use screener_company and get_symbol_data tools.
2. MOAT ASSESSMENT: Does the company have pricing power, switching costs, network effects, or cost advantages? Use sector/industry context from list_sectors and get_industry_stocks.
3. INTRINSIC VALUE: Calculate Graham Number (√(22.5 × EPS × Book Value)). Compare to current price. Assess margin of safety.
4. MANAGEMENT: Check promoter holding %, pledge %, insider transactions via screener_trades.
5. GROWTH CONTEXT: 5-year revenue and profit CAGR, Piotroski F-Score.
6. RED FLAGS: Declining ROCE, rising debt, promoter pledging >20%, frequent equity dilution, poor cash conversion.
7. PORTFOLIO CONSTRUCTION: When asked to build a value portfolio, select 8–15 stocks with strong quality scores (ROCE >15%, ROE >15%, D/E <1), then use `optimize_portfolio(objective='max_sharpe')` to find the optimal weight distribution. Save the result with `create_watchlist` and `bulk_replace_watchlist`.

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
6. PORTFOLIO CONSTRUCTION: Translate sector rotation views into concrete portfolios. Use `list_sectors` and `get_sector_stocks` to identify top-ranked stocks per sector, then use `optimize_portfolio(objective='risk_parity')` for a balanced sector-rotated portfolio. Save with `create_watchlist` and `bulk_replace_watchlist`.

Use get_global_news with threat_level filters to identify macro risks. Be explicit about the difference between short-term (1-3 months) and medium-term (6-12 months) views.""",
}


def _get_system_prompt(symbol: str, exchange: str, persona: str | None) -> str:
    """Build the system prompt, optionally prepending a persona definition."""
    if persona and persona in PERSONA_SYSTEM_PROMPTS:
        return PERSONA_SYSTEM_PROMPTS[persona] + f"\n\nCurrent symbol context: {symbol} on {exchange}."
    # No persona — fall back to the rich default system prompt
    return _build_system_prompt(symbol, exchange)


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
            "name": "screener_company",
            "description": _desc("screener_company"),
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Single NSE symbol. Mutually exclusive with symbols."},
                    "symbols": {"type": "array", "items": {"type": "string"}, "description": "Multiple NSE symbols. Mutually exclusive with symbol."},
                    "consolidated": {"type": "boolean", "description": "Use consolidated financials (default true); set false for standalone."},
                },
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
            "name": "get_corporate_filings",
            "description": _desc("get_corporate_filings"),
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
                    "refresh": {"type": "boolean", "description": "Force a live fetch from MoneyControl (default false)."},
                },
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
        get_corporate_filings,
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
        run_tql_screener,
        screener_company,
        screener_search,
        screener_trades,
        search_stock_universe,
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
        "screener_company": screener_company,
        "screener_trades": screener_trades,
        "run_tql_screener": run_tql_screener,
        "get_corporate_filings": get_corporate_filings,
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
- For a single stock: fetch fundamentals (screener_company), price data (get_symbol_data), and deal flow (screener_trades or get_bulk_deals) together when relevant — paint a complete picture.
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
- **Portfolio optimization**: Build and optimize portfolios using mean-variance (max Sharpe, min volatility) or hierarchical risk parity. Fetch a watchlist's symbols, run `optimize_portfolio`, interpret the weights and risk metrics, and save the result as a new or existing watchlist using `create_watchlist` and `bulk_replace_watchlist`.

## Output Format
- Lead with the key insight or number — not a preamble.
- Use markdown tables for multi-column data (prices, financials, comparisons).
- Format Indian numbers with Indian comma notation (1,23,456) or use Cr/L suffixes for large figures.
- When analyzing a stock, structure your response as: **Price context → Fundamentals → Catalysts/Risks → Verdict**.
- Cite which tools you called at the end of each response in italics (e.g., *Sources: screener_company, get_symbol_data*).
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
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Execute tool calls in parallel. Returns (sse_events, tool_result_messages) in OpenAI format."""

    async def _call(tc: dict[str, Any]) -> tuple[str, str, str]:
        tool_name = tc["name"]
        args = tc["args"]
        raw_args = json.dumps(args)
        call_key = f"{tool_name}:{raw_args}"

        already_seen = call_key in seen_calls
        seen_calls.add(call_key)

        if already_seen:
            content_str = json.dumps({"error": "Duplicate call — data already retrieved. Use it directly."})
        else:
            try:
                result = await asyncio.wait_for(_execute_tool(tool_name, args), timeout=120.0)
                content_str = _truncate_tool_result(result)
            except asyncio.TimeoutError:
                content_str = json.dumps({"error": f"{tool_name} timed out after 120s"})
            except Exception as exc:
                logger.warning("Tool %s failed: %s", tool_name, exc)
                content_str = json.dumps({"error": str(exc)})

        return tool_name, tc["id"], content_str

    results = await asyncio.gather(*[_call(tc) for tc in tool_calls])

    sse_events = []
    tool_msgs = []
    for tool_name, tool_id, content_str in results:
        preview = content_str[:120] + "..." if len(content_str) > 120 else content_str
        sse_events.append(json.dumps({"type": "tool_result", "name": tool_name, "preview": preview}))
        tool_msgs.append({"id": tool_id, "name": tool_name, "content": content_str})

    return sse_events, tool_msgs


# ---------------------------------------------------------------------------
# OpenAI loop — Kimi, Qwen, and other /chat/completions models
# ---------------------------------------------------------------------------


async def _run_openai_loop(
    messages: list[dict[str, Any]],
    model: str,
    api_key: str,
) -> AsyncGenerator[str, None]:
    url = f"{settings.zen_base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    seen_calls: set[str] = set()

    client = _get_shared_client()
    for _iteration in range(MAX_ITER):
        payload = {
            "model": model,
            "temperature": 0.6,
            "top_p": 0.95,
            "max_tokens": 4096,
            "tools": BLM_TOOLS,
            "tool_choice": "auto",
            "stream": True,
            "messages": messages,
        }

        try:
            async with client.stream("POST", url, json=payload, headers=headers) as response:
                if response.status_code != 200:
                    body = await response.aread()
                    yield json.dumps({"type": "error", "message": f"Zen API {response.status_code}: {body.decode()[:300]}"})
                    yield json.dumps({"type": "done"})
                    return

                content = ""
                reasoning = ""
                finish_reason: str | None = None
                tool_calls_map: dict[int, dict[str, Any]] = {}

                async for line in response.aiter_lines():
                    if not line.startswith("data: ") or line == "data: [DONE]":
                        continue
                    try:
                        chunk = json.loads(line[6:])
                    except json.JSONDecodeError:
                        continue

                    choices = chunk.get("choices")
                    if not choices:
                        continue
                    choice = choices[0]
                    finish_reason = choice.get("finish_reason") or finish_reason
                    delta = choice.get("delta", {})

                    if delta.get("reasoning_content"):
                        reasoning += delta["reasoning_content"]

                    if delta.get("content"):
                        content += delta["content"]
                        yield json.dumps({"type": "token", "text": delta["content"]})

                    for tc in delta.get("tool_calls", []):
                        idx = tc.get("index", 0)
                        if idx not in tool_calls_map:
                            tool_calls_map[idx] = {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
                        entry = tool_calls_map[idx]
                        entry["id"] += tc.get("id") or ""
                        fn = tc.get("function") or {}
                        entry["function"]["name"] += fn.get("name") or ""
                        entry["function"]["arguments"] += fn.get("arguments") or ""

        except httpx.RequestError as exc:
            yield json.dumps({"type": "error", "message": f"Network error: {exc}"})
            yield json.dumps({"type": "done"})
            return

        tool_calls_list = [tool_calls_map[i] for i in sorted(tool_calls_map)]

        # Reconstruct assistant message preserving reasoning for multi-turn quality
        assistant_msg: dict[str, Any] = {"role": "assistant", "content": content or None}
        if reasoning:
            assistant_msg["reasoning_content"] = reasoning
        if tool_calls_list:
            assistant_msg["tool_calls"] = tool_calls_list
        messages.append(assistant_msg)

        if finish_reason == "stop" or (finish_reason is None and not tool_calls_list):
            yield json.dumps({"type": "done"})
            return

        if tool_calls_list:
            # Yield tool_call events before executing
            for tc in tool_calls_list:
                try:
                    args_preview = json.loads(tc["function"]["arguments"]) if tc["function"]["arguments"] else {}
                except json.JSONDecodeError:
                    args_preview = {}
                yield json.dumps({"type": "tool_call", "name": tc["function"]["name"], "args": args_preview})

            # Normalise for shared executor
            normalised = [
                {"id": tc["id"], "name": tc["function"]["name"], "args": json.loads(tc["function"]["arguments"]) if tc["function"]["arguments"] else {}}
                for tc in tool_calls_list
            ]
            sse_events, tool_msgs = await _run_tools_parallel(normalised, seen_calls)

            for ev in sse_events:
                yield ev

            for tm in tool_msgs:
                messages.append({"role": "tool", "tool_call_id": tm["id"], "content": tm["content"]})
            continue

        yield json.dumps({"type": "done"})
        return

    yield json.dumps({"type": "error", "message": f"Agent exceeded {MAX_ITER} iterations. Try a more specific question."})
    yield json.dumps({"type": "done"})


# ---------------------------------------------------------------------------
# Anthropic loop — MiniMax M2.5 and M2.7 via /messages
# ---------------------------------------------------------------------------


async def _run_anthropic_loop(
    messages: list[dict[str, Any]],
    system_prompt: str,
    model: str,
    api_key: str,
) -> AsyncGenerator[str, None]:
    url = f"{settings.zen_base_url}/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    seen_calls: set[str] = set()

    client = _get_shared_client()
    for _iteration in range(MAX_ITER):
        payload = {
            "model": model,
            "max_tokens": 4096,
            "system": system_prompt,
            "tools": BLM_TOOLS_ANTHROPIC,
            "stream": True,
            "messages": messages,
        }

        try:
            async with client.stream("POST", url, json=payload, headers=headers) as response:
                if response.status_code != 200:
                    body = await response.aread()
                    yield json.dumps({"type": "error", "message": f"Zen API {response.status_code}: {body.decode()[:300]}"})
                    yield json.dumps({"type": "done"})
                    return

                # Anthropic SSE: track content blocks by index
                # block_types[idx] = "text" | "tool_use" | "thinking"
                block_types: dict[int, str] = {}
                block_ids: dict[int, str] = {}
                block_names: dict[int, str] = {}
                block_args: dict[int, str] = {}
                block_text: dict[int, str] = {}
                stop_reason: str | None = None

                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if not raw or raw == "[DONE]":
                        continue
                    try:
                        ev = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    etype = ev.get("type", "")

                    if etype == "content_block_start":
                        idx = ev["index"]
                        block = ev.get("content_block", {})
                        btype = block.get("type", "")
                        block_types[idx] = btype
                        if btype == "tool_use":
                            block_ids[idx] = block.get("id", "")
                            block_names[idx] = block.get("name", "")
                            block_args[idx] = ""
                        elif btype == "text":
                            block_text[idx] = ""

                    elif etype == "content_block_delta":
                        idx = ev["index"]
                        delta = ev.get("delta", {})
                        dtype = delta.get("type", "")

                        if dtype == "text_delta":
                            text = delta.get("text", "")
                            block_text[idx] = block_text.get(idx, "") + text
                            yield json.dumps({"type": "token", "text": text})

                        elif dtype == "input_json_delta":
                            block_args[idx] = block_args.get(idx, "") + delta.get("partial_json", "")

                        # thinking_delta — ignore for output, not stored

                    elif etype == "message_delta":
                        stop_reason = ev.get("delta", {}).get("stop_reason")

        except httpx.RequestError as exc:
            yield json.dumps({"type": "error", "message": f"Network error: {exc}"})
            yield json.dumps({"type": "done"})
            return

        # Reconstruct full content array for history (Anthropic requires this)
        content_blocks: list[dict[str, Any]] = []
        tool_use_indices: list[int] = []

        for idx in sorted(block_types):
            btype = block_types[idx]
            if btype == "text":
                text_val = block_text.get(idx, "")
                if text_val:
                    content_blocks.append({"type": "text", "text": text_val})
            elif btype == "tool_use":
                try:
                    input_val = json.loads(block_args.get(idx, "{}") or "{}")
                except json.JSONDecodeError:
                    input_val = {}
                content_blocks.append({
                    "type": "tool_use",
                    "id": block_ids[idx],
                    "name": block_names[idx],
                    "input": input_val,
                })
                tool_use_indices.append(idx)
            # thinking blocks are intentionally omitted from reconstructed history
            # (MiniMax on Go does not require them to be echoed back)

        messages.append({"role": "assistant", "content": content_blocks})

        if stop_reason == "end_turn" or (stop_reason is None and not tool_use_indices):
            yield json.dumps({"type": "done"})
            return

        if tool_use_indices:
            # Yield tool_call events
            for idx in tool_use_indices:
                try:
                    args_preview = json.loads(block_args.get(idx, "{}") or "{}")
                except json.JSONDecodeError:
                    args_preview = {}
                yield json.dumps({"type": "tool_call", "name": block_names[idx], "args": args_preview})

            # Normalise for shared executor
            normalised = [
                {
                    "id": block_ids[idx],
                    "name": block_names[idx],
                    "args": json.loads(block_args.get(idx, "{}") or "{}"),
                }
                for idx in tool_use_indices
            ]
            sse_events, tool_msgs = await _run_tools_parallel(normalised, seen_calls)

            for ev in sse_events:
                yield ev

            # Anthropic tool results go back as a single user turn with tool_result blocks
            tool_result_blocks = [
                {"type": "tool_result", "tool_use_id": tm["id"], "content": tm["content"]}
                for tm in tool_msgs
            ]
            messages.append({"role": "user", "content": tool_result_blocks})
            continue

        yield json.dumps({"type": "done"})
        return

    yield json.dumps({"type": "error", "message": f"Agent exceeded {MAX_ITER} iterations. Try a more specific question."})
    yield json.dumps({"type": "done"})


# ---------------------------------------------------------------------------
# Public entry point — dispatches to the correct loop
# ---------------------------------------------------------------------------


async def run_chat_agent(
    messages: list[dict[str, Any]],
    symbol: str,
    exchange: str,
    model: str = "kimi-k2.5",
    persona: str | None = None,
) -> AsyncGenerator[str, None]:
    """Run the agentic loop and yield SSE-formatted JSON strings.

    Yielded event formats:
      {"type": "token", "text": "..."}
      {"type": "tool_call", "name": "...", "args": {...}}
      {"type": "tool_result", "name": "...", "preview": "..."}
      {"type": "error", "message": "..."}
      {"type": "done"}
    """
    api_key = settings.opencode_zen_api_key
    if not api_key or api_key == "none":
        yield json.dumps({"type": "error", "message": "OPENCODE_ZEN_API_KEY is not configured."})
        yield json.dumps({"type": "done"})
        return

    system_prompt = _get_system_prompt(symbol, exchange, persona)

    if model in ANTHROPIC_MODELS:
        # Anthropic format: system prompt is a top-level field, not a message
        # Convert any existing system messages in history to a user context note
        anthropic_messages = [m for m in messages if m.get("role") != "system"]
        async for chunk in _run_anthropic_loop(anthropic_messages, system_prompt, model, api_key):
            yield chunk
    else:
        # OpenAI format: system prompt is first message
        full_messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            *messages,
        ]
        async for chunk in _run_openai_loop(full_messages, model, api_key):
            yield chunk
