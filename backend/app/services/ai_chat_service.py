"""AI Chat Service — dual-format agentic loop via OpenCode Go.

Two wire formats are supported:
  - OpenAI /chat/completions  — Kimi, Qwen, and other Go models
  - Anthropic /messages       — MiniMax M2.5 and M2.7 on Go

Both loops yield the same SSE-compatible JSON strings so the router and
frontend are completely format-agnostic.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

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
# Tool definitions — OpenAI /chat/completions format
# ---------------------------------------------------------------------------

BLM_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "health_check",
            "description": "Check backend service health and connectivity.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_top_gainers",
            "description": "Fetch today's top-gaining NSE equities ranked by intraday percentage change. Use for market movers, top performers, or best stocks today.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_top_losers",
            "description": "Fetch today's top-losing NSE equities ranked by intraday percentage change. Use for worst performers, biggest decliners today.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_bulk_deals",
            "description": "Fetch today's NSE bulk deal records for one or multiple symbols. Use for institutional buying/selling activity. NOTE: only today's deals — for historical bulk deals use screener_trades.",
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
            "description": "Fetch today's NSE block deal records for one or multiple symbols. Use for large block trades. NOTE: only today's deals — for historical block deals use screener_trades.",
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
            "description": "Fetch a combined real-time snapshot of NSE insider, bulk, and block deals across all stocks. Use for a broad picture of large deal activity.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_change_ranges",
            "description": "Fetch NSE percentage price changes across multiple timeframes (1w, 1m, 3m, 6m, 1y, 2y, 3y, 5y) for one or multiple symbols. Use for performance analysis, momentum scoring, or return comparisons.",
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
            "description": "Fetch live NSE quote data: LTP (last traded price), 52-week high/low, sector, and industry. Use for current price, valuation range context, or sector identification.",
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
            "description": "Fetch NSE stocks that crossed a new 52-week low today. Use for stocks at yearly lows, potential value opportunities, or breakdown candidates.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_52week_high_stocks",
            "description": "Fetch NSE stocks that crossed a new 52-week high today. Use for breakout stocks, momentum leaders, or all-time-high candidates.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_volume_gainers",
            "description": "Fetch NSE stocks with the largest volume surge relative to their weekly average. Use for unusual activity, potential breakouts, or stocks attracting institutional attention.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "screener_search",
            "description": "Search screener.in for NSE companies by name or symbol fragment. Use to resolve a company name to its NSE symbol before calling other tools.",
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
            "description": "Fetch fundamental ratios and quarterly results for NSE companies from screener.in. Returns P/E, ROCE, ROE, debt-to-equity, sales growth, profit growth, and last 4 quarters of financials. Use for fundamental analysis, quality screening, or earnings trend assessment.",
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
            "description": "Fetch historical insider trades, bulk deals, and block deals for NSE companies from screener.in. Use for multi-year deal history and promoter activity patterns. Do NOT use for today's deals — use get_bulk_deals or get_block_deals instead.",
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
            "name": "get_corporate_filings",
            "description": "Fetch NSE quarterly corporate filing results as structured CSV data. Use for detailed quarterly P&L, revenue, and EPS figures.",
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
            "description": "List all tracked NSE stocks with symbol, company name, sector, industry, and PE data. Use to browse the full investable universe or scan for stocks by sector.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_stock_universe",
            "description": "Look up NSE stock universe metadata (sector, industry, PE) for one or multiple symbols. Prefer screener_company for deeper fundamental research.",
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
            "description": "Search tracked NSE stocks by symbol or company name prefix.",
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
            "description": "List all items in the user's default watchlist (ID 1). Returns symbol, exchange, and timestamp.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_watchlists",
            "description": "List all user-created watchlists with name and item count.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_watchlist_items",
            "description": "Fetch all symbol/exchange items in a watchlist by its numeric ID.",
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
            "name": "get_notifications",
            "description": "Fetch unread market-event notifications for a specific watchlist. Returns alerts like 52w highs, volume breakouts, RSI signals for watched stocks.",
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
            "description": "Fetch unread global NSE scan alerts across all stocks. Filter by trigger_type for specific signal categories.",
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
            "description": "Fetch Morningstar fair value estimate and uncertainty rating for one or multiple NSE symbols. Use for valuation gap analysis — compare fair value vs current price to identify overvalued or undervalued stocks.",
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
            "description": "Fetch recent global financial news from MoneyControl. Use for macro events, market-wide headlines, RBI/government policy news, or FII/DII flow stories.",
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
            "description": "Fetch MoneyControl news for one or multiple NSE companies. Use for company-specific catalysts, earnings coverage, management commentary, or corporate announcements.",
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
            "description": "List all NSE industries with market cap, PE ratio, advance/decline counts, and sentiment. Use for sector rotation analysis, identifying hot/cold industries, or market breadth assessment.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_sectors",
            "description": "List all NSE sectors with market cap, PE ratio, advance/decline counts, and sentiment. Use for broad sector analysis or thematic investing.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_industry_stocks",
            "description": "Fetch all NSE stocks in a given industry, sorted by market cap. Use list_industries() first to get valid slugs.",
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
            "description": "Fetch all NSE stocks in a given sector, sorted by market cap. Use list_sectors() first to get valid slugs.",
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
        health_check,
        list_industries,
        list_sectors,
        list_stock_universe,
        list_watchlist,
        list_watchlists,
        screener_company,
        screener_search,
        screener_trades,
        search_stock_universe,
    )

    dispatch: dict[str, Any] = {
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
- **Sector rotation**: Industry and sector PE, advance/decline, sentiment, top stocks by market cap
- **News & catalysts**: Company-specific news, earnings announcements, macro events affecting the market
- **Watchlist analysis**: Review held positions, flag signals across watched stocks

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
                result = await asyncio.wait_for(_execute_tool(tool_name, args), timeout=30.0)
                content_str = _truncate_tool_result(result)
            except asyncio.TimeoutError:
                content_str = json.dumps({"error": f"{tool_name} timed out after 30s"})
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

    async with httpx.AsyncClient(timeout=120.0) as client:
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

    async with httpx.AsyncClient(timeout=120.0) as client:
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

    system_prompt = _build_system_prompt(symbol, exchange)

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
