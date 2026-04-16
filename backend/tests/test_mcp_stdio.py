"""
In-process tests for the MCP stdio entrypoint (run_mcp_stdio.py).

These tests use the MCP SDK's in-process memory transport
(`create_connected_server_and_client_session`) so no live server is required.

Key pattern: use ONE session per call_tool invocation.  Making multiple
`call_tool` calls inside a single context causes a KeyError/ExceptionGroup on
teardown due to an anyio limitation in the memory transport.  Each assertion
therefore opens its own `async with create_connected_server_and_client_session`
block.

asyncio_mode = "auto" is already set in pyproject.toml, so no
@pytest.mark.asyncio decorator is needed.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

# ---------------------------------------------------------------------------
# Load run_mcp_stdio.py as a module without running mcp.run()
# ---------------------------------------------------------------------------

_STDIO_PATH = Path(__file__).parent.parent / "run_mcp_stdio.py"


def _load_stdio_module():
    spec = importlib.util.spec_from_file_location("run_mcp_stdio", _STDIO_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_stdio_mod = _load_stdio_module()
mcp = _stdio_mod.mcp

KNOWN_SYMBOL = "RELIANCE"
KNOWN_PREFIX = "RELI"

EXPECTED_TOOLS = {
    "health_check",
    "get_top_gainers",
    "get_top_losers",
    "get_bulk_deals",
    "get_block_deals",
    "get_high_short_interest",
    "get_largedeal_snapshot",
    "get_change_ranges",
    "get_symbol_data",
    "get_52week_low_stocks",
    "get_52week_high_stocks",
    "get_volume_gainers",
    "get_corporate_filings",
    "screener_search",
    "screener_company",
    "screener_trades",
    "get_company_quarterly_results",
    "list_stock_universe",
    "get_stock_universe",
    "search_stock_universe",
    "list_watchlist",
    "get_watchlist_symbols",
    "add_watchlist_item",
    "remove_watchlist_item",
    "list_watchlists",
    "get_watchlist_items",
    "get_notifications",
    "get_global_notifications",
    "get_morningstar_fairvalue",
    "get_global_news",
    "get_company_news",
    "list_industries",
    "list_sectors",
    "get_industry_stocks",
    "get_sector_stocks",
}


# ---------------------------------------------------------------------------
# Module / instance tests (synchronous — no transport needed)
# ---------------------------------------------------------------------------


class TestStdioModuleStructure:
    """Verify run_mcp_stdio.py exports the correct FastMCP instance."""

    def test_mcp_attribute_exists(self):
        assert hasattr(_stdio_mod, "mcp"), "run_mcp_stdio must export 'mcp'"

    def test_mcp_name(self):
        assert mcp.name == "BLM Analytics"

    def test_mcp_stateless_http(self):
        # FastMCP stores settings under mcp.settings (a pydantic Settings object)
        assert mcp.settings.stateless_http is True

    def test_mcp_json_response(self):
        assert mcp.settings.json_response is True

    def test_no_main_side_effects(self):
        """Importing the module must not call mcp.run() or block."""
        # If we got here, the import completed without blocking — test passes.
        assert True


# ---------------------------------------------------------------------------
# In-process transport tests
# ---------------------------------------------------------------------------


class TestMCPToolDiscovery:
    """Tool discovery via in-process transport."""

    async def test_list_tools_returns_tools(self):
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.list_tools()
        assert len(result.tools) > 0

    async def test_all_expected_tools_present(self):
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.list_tools()
        names = {t.name for t in result.tools}
        assert EXPECTED_TOOLS.issubset(names)

    async def test_every_tool_has_description(self):
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.list_tools()
        for tool in result.tools:
            assert tool.description, f"Tool '{tool.name}' has no description"


# ---------------------------------------------------------------------------
# Tool call tests — one session per call
# ---------------------------------------------------------------------------


class TestMCPHealthCheck:
    async def test_health_check_returns_ok(self):
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool("health_check", {})
        assert not result.isError
        assert len(result.content) > 0
        data = json.loads(result.content[0].text)
        assert data.get("status") == "ok"


class TestMCPStockUniverse:
    async def test_list_stock_universe_returns_list(self):
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool("list_stock_universe", {})
        # The in-process transport serializes each list item as a separate
        # TextContent entry; a non-empty DB will produce multiple content items.
        assert not result.isError
        assert len(result.content) > 0
        # Each content entry must be valid JSON representing a stock record
        first = json.loads(result.content[0].text)
        assert isinstance(first, dict)
        assert "symbol" in first

    async def test_get_stock_universe_known_symbol(self):
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool(
                "get_stock_universe", {"symbol": KNOWN_SYMBOL}
            )
        assert not result.isError
        data = json.loads(result.content[0].text)
        assert isinstance(data, dict)
        assert data.get("symbol") == KNOWN_SYMBOL

    async def test_get_stock_universe_unknown_symbol_is_error(self):
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool(
                "get_stock_universe", {"symbol": "NOTEXIST999"}
            )
        assert result.isError
        assert len(result.content) > 0
        assert "not found" in result.content[0].text.lower()

    async def test_get_stock_universe_invalid_symbol_format(self):
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool(
                "get_stock_universe", {"symbol": "INVALID@@@"}
            )
        # Invalid characters trigger either a validation error or not-found error
        assert result.isError
        assert len(result.content) > 0

    async def test_search_stock_universe_returns_matches(self):
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool(
                "search_stock_universe", {"prefix": KNOWN_PREFIX}
            )
        # Same per-item serialisation as list_stock_universe
        assert not result.isError
        assert len(result.content) > 0
        first = json.loads(result.content[0].text)
        assert isinstance(first, dict)
        assert "symbol" in first

    async def test_search_stock_universe_no_matches(self):
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool(
                "search_stock_universe", {"prefix": "ZZZNOMATCH99999"}
            )
        # No matching rows → empty content list (not an error)
        assert not result.isError
        assert len(result.content) == 0


class TestMCPScreener:
    async def test_screener_search_known_query(self):
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool("screener_search", {"q": "reliance"})
        # screener_search may fail if ScreenerClient.init() hasn't been called
        # (requires browser session).  Accept either a valid result list or an
        # isError response; the important thing is that the tool is reachable and
        # does not raise an unhandled exception.
        assert len(result.content) > 0
        if not result.isError:
            data = json.loads(result.content[0].text)
            # Each list item is a separate TextContent; the first must be a dict
            assert isinstance(data, dict)

    async def test_screener_search_empty_query_is_error(self):
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool("screener_search", {"q": ""})
        assert result.isError
        assert len(result.content) > 0


class TestMCPErrorHandling:
    async def test_unknown_tool_is_error(self):
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool("nonexistent_tool", {})
        assert result.isError
        assert len(result.content) > 0
        assert "unknown tool" in result.content[0].text.lower()


class TestMCPScreenerQuarterly:
    """In-process tests for the get_company_quarterly_results MCP tool."""

    async def test_tool_is_listed(self):
        """get_company_quarterly_results must appear in the tools list."""
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.list_tools()
        names = {t.name for t in result.tools}
        assert "get_company_quarterly_results" in names

    async def test_tool_has_description(self):
        """Tool must carry a non-empty description."""
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.list_tools()
        tool = next(
            t for t in result.tools if t.name == "get_company_quarterly_results"
        )
        assert tool.description, "get_company_quarterly_results has no description"

    async def test_call_returns_content_or_auth_error(self):
        """
        Returns structured data when authenticated; isError=True when no
        screener.in session is available.  Either outcome is valid — the
        important thing is the tool is reachable and does not raise unhandled.
        """
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool(
                "get_company_quarterly_results", {"symbol": KNOWN_SYMBOL}
            )
        assert len(result.content) > 0
        # Content must be parseable text regardless of success/failure
        assert result.content[0].text

    async def test_success_response_has_correct_schema(self):
        """On success the first content item must include symbol and quarterly_results."""
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool(
                "get_company_quarterly_results", {"symbol": KNOWN_SYMBOL}
            )
        if result.isError:
            pytest.skip("screener.in session not available (auth error)")
        data = json.loads(result.content[0].text)
        assert "symbol" in data
        assert "consolidated" in data
        assert "quarterly_results" in data
        assert isinstance(data["quarterly_results"], dict)

    async def test_quarterly_results_year_month_nesting(self):
        """quarterly_results must be year → month → {metric: value}."""
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool(
                "get_company_quarterly_results", {"symbol": KNOWN_SYMBOL}
            )
        if result.isError:
            pytest.skip("screener.in session not available")
        data = json.loads(result.content[0].text)
        qr = data.get("quarterly_results", {})
        if not qr:
            pytest.skip("quarterly_results is empty")
        for year_key, months in qr.items():
            assert isinstance(months, dict), f"Expected dict under year '{year_key}'"
            for month_key, metrics in months.items():
                assert isinstance(metrics, dict), (
                    f"Expected dict under '{year_key}.{month_key}'"
                )

    async def test_invalid_symbol_is_error(self):
        """Invalid symbol characters must produce isError=True."""
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool(
                "get_company_quarterly_results", {"symbol": "INVALID@@@"}
            )
        assert result.isError
        assert len(result.content) > 0


# ---------------------------------------------------------------------------
# Watchlist CRUD tests (existing tools)
# ---------------------------------------------------------------------------


class TestMCPWatchlistTools:
    """In-process tests for watchlist CRUD tools."""

    async def test_list_watchlist_returns_list(self):
        """list_watchlist returns a list of items."""
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool("list_watchlist", {})
        assert not result.isError
        assert len(result.content) > 0

    async def test_get_watchlist_symbols_returns_strings(self):
        """get_watchlist_symbols returns a list of symbol strings."""
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool("get_watchlist_symbols", {})
        assert not result.isError
        assert len(result.content) > 0

    async def test_add_watchlist_item_returns_dict(self):
        """add_watchlist_item returns a dict with id, symbol, exchange."""
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool(
                "add_watchlist_item", {"symbol": "TESTST", "exchange": "NSE"}
            )
        assert not result.isError
        assert len(result.content) > 0
        data = json.loads(result.content[0].text)
        assert "id" in data
        assert data["symbol"] == "TESTST"
        assert data["exchange"] == "NSE"

    async def test_add_watchlist_item_idempotent(self):
        """Adding the same item twice returns the same id."""
        async with create_connected_server_and_client_session(mcp) as client:
            result1 = await client.call_tool(
                "add_watchlist_item", {"symbol": "IDEMST", "exchange": "NSE"}
            )
        data1 = json.loads(result1.content[0].text)
        id1 = data1["id"]

        async with create_connected_server_and_client_session(mcp) as client:
            result2 = await client.call_tool(
                "add_watchlist_item", {"symbol": "IDEMST", "exchange": "NSE"}
            )
        data2 = json.loads(result2.content[0].text)
        id2 = data2["id"]

        assert id1 == id2

    async def test_add_watchlist_item_normalizes_case(self):
        """add_watchlist_item normalizes symbol to uppercase."""
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool(
                "add_watchlist_item", {"symbol": "lower", "exchange": "nse"}
            )
        data = json.loads(result.content[0].text)
        assert data["symbol"] == "LOWER"
        assert data["exchange"] == "NSE"

    async def test_add_watchlist_item_missing_exchange_is_error(self):
        """add_watchlist_item without exchange returns isError."""
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool(
                "add_watchlist_item", {"symbol": "TESTST"}
            )
        assert result.isError

    async def test_remove_watchlist_item_returns_ok(self):
        """remove_watchlist_item returns ok=True when item exists."""
        async with create_connected_server_and_client_session(mcp) as client:
            add_result = await client.call_tool(
                "add_watchlist_item", {"symbol": "DELTEST", "exchange": "NSE"}
            )
        item = json.loads(add_result.content[0].text)
        item_id = item["id"]

        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool(
                "remove_watchlist_item", {"item_id": item_id}
            )
        assert not result.isError
        data = json.loads(result.content[0].text)
        assert data.get("ok") is True

    async def test_remove_watchlist_item_nonexistent_is_error(self):
        """remove_watchlist_item with invalid id returns isError."""
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool(
                "remove_watchlist_item", {"item_id": 999999}
            )
        assert result.isError


# ---------------------------------------------------------------------------
# New watchlist tools: list_watchlists, get_watchlist_items
# ---------------------------------------------------------------------------


class TestMCPNewWatchlistTools:
    """In-process tests for list_watchlists and get_watchlist_items."""

    async def test_list_watchlists_returns_list(self):
        """list_watchlists returns a list (possibly empty)."""
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool("list_watchlists", {})
        assert not result.isError
        assert len(result.content) > 0

    async def test_get_watchlist_items_nonexistent_is_error(self):
        """get_watchlist_items with nonexistent id returns isError."""
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool(
                "get_watchlist_items", {"watchlist_id": 999999}
            )
        assert result.isError


# ---------------------------------------------------------------------------
# Notification tools
# ---------------------------------------------------------------------------


class TestMCPNotificationTools:
    """In-process tests for notification tools."""

    async def test_get_notifications_returns_list(self):
        """get_notifications returns a list (possibly empty)."""
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool("get_notifications", {"watchlist_id": 1})
        assert not result.isError
        assert len(result.content) > 0

    async def test_get_global_notifications_returns_list(self):
        """get_global_notifications with limit returns a list (possibly empty)."""
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool(
                "get_global_notifications", {"limit": 5}
            )
        assert not result.isError
        assert len(result.content) > 0


# ---------------------------------------------------------------------------
# Morningstar tool
# ---------------------------------------------------------------------------


class TestMCPMorningstarTool:
    """In-process tests for get_morningstar_fairvalue."""

    async def test_single_symbol_callable(self):
        """get_morningstar_fairvalue with single symbol is callable."""
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool(
                "get_morningstar_fairvalue", {"symbol": "RELIANCE"}
            )
        assert len(result.content) > 0
        assert result.content[0].text

    async def test_neither_param_is_error(self):
        """Neither symbol nor symbols returns isError."""
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool(
                "get_morningstar_fairvalue", {}
            )
        assert result.isError

    async def test_both_params_is_error(self):
        """Both symbol and symbols returns isError."""
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool(
                "get_morningstar_fairvalue",
                {"symbol": "RELIANCE", "symbols": ["TCS"]},
            )
        assert result.isError


# ---------------------------------------------------------------------------
# Company news tool
# ---------------------------------------------------------------------------


class TestMCPCompanyNews:
    """In-process tests for get_company_news."""

    async def test_single_symbol_callable(self):
        """get_company_news with single symbol is callable."""
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool(
                "get_company_news", {"symbol": "RELIANCE", "refresh": False}
            )
        assert len(result.content) > 0
        assert result.content[0].text

    async def test_neither_param_is_error(self):
        """Neither symbol nor symbols returns isError."""
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool("get_company_news", {})
        assert result.isError

    async def test_both_params_is_error(self):
        """Both symbol and symbols returns isError."""
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool(
                "get_company_news",
                {"symbol": "RELIANCE", "symbols": ["TCS"]},
            )
        assert result.isError


# ---------------------------------------------------------------------------
# Global news tool
# ---------------------------------------------------------------------------


class TestMCPGlobalNews:
    """In-process tests for get_global_news."""

    async def test_returns_list(self):
        """get_global_news returns a list (possibly empty)."""
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool("get_global_news", {})
        assert not result.isError
        assert len(result.content) > 0


# ---------------------------------------------------------------------------
# Industry and sector tools
# ---------------------------------------------------------------------------


class TestMCPIndustrySector:
    """In-process tests for industry and sector tools."""

    async def test_list_industries_returns_list_with_slug(self):
        """list_industries returns list with slug field."""
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool("list_industries", {})
        assert not result.isError
        assert len(result.content) > 0
        first = json.loads(result.content[0].text)
        assert "slug" in first

    async def test_list_sectors_returns_list(self):
        """list_sectors returns list (possibly empty)."""
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool("list_sectors", {})
        assert not result.isError
        # Sectors may be empty in test DB - check either content or structuredContent
        if result.content:
            data = json.loads(result.content[0].text)
        else:
            data = result.structuredContent.get("result", [])
        assert isinstance(data, list)

    async def test_get_industry_stocks_valid_slug(self):
        """get_industry_stocks with valid slug returns list (possibly empty)."""
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool(
                "get_industry_stocks", {"slug": "bank-private"}
            )
        assert not result.isError
        assert len(result.content) > 0

    async def test_get_industry_stocks_invalid_slug_is_error(self):
        """get_industry_stocks with invalid slug returns isError."""
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool(
                "get_industry_stocks", {"slug": "NOTEXIST999"}
            )
        assert result.isError

    async def test_get_sector_stocks_invalid_slug_is_error(self):
        """get_sector_stocks with invalid slug returns isError."""
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool(
                "get_sector_stocks", {"slug": "nonexistent-sector"}
            )
        assert result.isError


# ---------------------------------------------------------------------------
# Bulk symbol tests for all 11 symbol-taking tools
# ---------------------------------------------------------------------------


class TestMCPBulkSymbolTools:
    """In-process tests for bulk symbol parameter on all tools that support it."""

    async def test_get_bulk_deals_bulk_returns_dict(self):
        """get_bulk_deals with symbols returns dict keyed by symbol."""
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool(
                "get_bulk_deals", {"symbols": ["RELIANCE", "TCS"]}
            )
        assert not result.isError
        data = json.loads(result.content[0].text)
        assert isinstance(data, dict)
        assert "RELIANCE" in data
        assert "TCS" in data

    async def test_get_bulk_deals_neither_param_is_error(self):
        """get_bulk_deals with neither param returns isError."""
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool("get_bulk_deals", {})
        assert result.isError

    async def test_get_bulk_deals_both_params_is_error(self):
        """get_bulk_deals with both params returns isError."""
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool(
                "get_bulk_deals", {"symbol": "RELIANCE", "symbols": ["TCS"]}
            )
        assert result.isError

    async def test_get_block_deals_bulk_returns_dict(self):
        """get_block_deals with symbols returns dict keyed by symbol."""
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool(
                "get_block_deals", {"symbols": ["RELIANCE", "TCS"]}
            )
        assert not result.isError
        data = json.loads(result.content[0].text)
        assert isinstance(data, dict)
        assert "RELIANCE" in data
        assert "TCS" in data

    async def test_get_block_deals_neither_param_is_error(self):
        """get_block_deals with neither param returns isError."""
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool("get_block_deals", {})
        assert result.isError

    async def test_get_block_deals_both_params_is_error(self):
        """get_block_deals with both params returns isError."""
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool(
                "get_block_deals", {"symbol": "RELIANCE", "symbols": ["TCS"]}
            )
        assert result.isError

    async def test_get_change_ranges_bulk_returns_dict(self):
        """get_change_ranges with symbols returns dict keyed by symbol."""
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool(
                "get_change_ranges", {"symbols": ["RELIANCE", "TCS"]}
            )
        assert not result.isError
        data = json.loads(result.content[0].text)
        assert isinstance(data, dict)
        assert "RELIANCE" in data
        assert "TCS" in data

    async def test_get_change_ranges_neither_param_is_error(self):
        """get_change_ranges with neither param returns isError."""
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool("get_change_ranges", {})
        assert result.isError

    async def test_get_change_ranges_both_params_is_error(self):
        """get_change_ranges with both params returns isError."""
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool(
                "get_change_ranges", {"symbol": "RELIANCE", "symbols": ["TCS"]}
            )
        assert result.isError

    async def test_get_symbol_data_bulk_returns_dict(self):
        """get_symbol_data with symbols returns dict keyed by symbol."""
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool(
                "get_symbol_data", {"symbols": ["RELIANCE", "TCS"]}
            )
        assert not result.isError
        data = json.loads(result.content[0].text)
        assert isinstance(data, dict)
        assert "RELIANCE" in data
        assert "TCS" in data

    async def test_get_symbol_data_neither_param_is_error(self):
        """get_symbol_data with neither param returns isError."""
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool("get_symbol_data", {})
        assert result.isError

    async def test_get_symbol_data_both_params_is_error(self):
        """get_symbol_data with both params returns isError."""
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool(
                "get_symbol_data", {"symbol": "RELIANCE", "symbols": ["TCS"]}
            )
        assert result.isError

    async def test_get_corporate_filings_bulk_returns_dict(self):
        """get_corporate_filings with symbols returns dict keyed by symbol."""
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool(
                "get_corporate_filings", {"symbols": ["RELIANCE", "TCS"]}
            )
        assert not result.isError
        data = json.loads(result.content[0].text)
        assert isinstance(data, dict)
        assert "RELIANCE" in data
        assert "TCS" in data

    async def test_get_corporate_filings_neither_param_is_error(self):
        """get_corporate_filings with neither param returns isError."""
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool("get_corporate_filings", {})
        assert result.isError

    async def test_get_corporate_filings_both_params_is_error(self):
        """get_corporate_filings with both params returns isError."""
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool(
                "get_corporate_filings", {"symbol": "RELIANCE", "symbols": ["TCS"]}
            )
        assert result.isError

    async def test_screener_company_bulk_returns_dict(self):
        """screener_company with symbols returns dict keyed by symbol."""
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool(
                "screener_company", {"symbols": ["RELIANCE", "TCS"]}
            )
        assert len(result.content) > 0
        if not result.isError:
            data = json.loads(result.content[0].text)
            assert isinstance(data, dict)

    async def test_screener_company_neither_param_is_error(self):
        """screener_company with neither param returns isError."""
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool("screener_company", {})
        assert result.isError

    async def test_screener_company_both_params_is_error(self):
        """screener_company with both params returns isError."""
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool(
                "screener_company", {"symbol": "RELIANCE", "symbols": ["TCS"]}
            )
        assert result.isError

    async def test_screener_trades_bulk_returns_dict(self):
        """screener_trades with symbols returns dict keyed by symbol."""
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool(
                "screener_trades", {"symbols": ["RELIANCE", "TCS"]}
            )
        assert len(result.content) > 0
        if not result.isError:
            data = json.loads(result.content[0].text)
            assert isinstance(data, dict)

    async def test_screener_trades_neither_param_is_error(self):
        """screener_trades with neither param returns isError."""
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool("screener_trades", {})
        assert result.isError

    async def test_screener_trades_both_params_is_error(self):
        """screener_trades with both params returns isError."""
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool(
                "screener_trades", {"symbol": "RELIANCE", "symbols": ["TCS"]}
            )
        assert result.isError

    async def test_get_company_quarterly_results_bulk_returns_dict(self):
        """get_company_quarterly_results with symbols returns dict keyed by symbol."""
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool(
                "get_company_quarterly_results", {"symbols": ["RELIANCE", "TCS"]}
            )
        assert len(result.content) > 0
        if not result.isError:
            data = json.loads(result.content[0].text)
            assert isinstance(data, dict)

    async def test_get_company_quarterly_results_neither_param_is_error(self):
        """get_company_quarterly_results with neither param returns isError."""
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool("get_company_quarterly_results", {})
        assert result.isError

    async def test_get_company_quarterly_results_both_params_is_error(self):
        """get_company_quarterly_results with both params returns isError."""
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool(
                "get_company_quarterly_results",
                {"symbol": "RELIANCE", "symbols": ["TCS"]},
            )
        assert result.isError

    async def test_get_stock_universe_bulk_returns_dict(self):
        """get_stock_universe with symbols returns dict keyed by symbol."""
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool(
                "get_stock_universe", {"symbols": ["RELIANCE", "TCS"]}
            )
        assert not result.isError
        data = json.loads(result.content[0].text)
        assert isinstance(data, dict)
        assert "RELIANCE" in data
        assert "TCS" in data

    async def test_get_stock_universe_neither_param_is_error(self):
        """get_stock_universe with neither param returns isError."""
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool("get_stock_universe", {})
        assert result.isError

    async def test_get_stock_universe_both_params_is_error(self):
        """get_stock_universe with both params returns isError."""
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool(
                "get_stock_universe", {"symbol": "RELIANCE", "symbols": ["TCS"]}
            )
        assert result.isError

    async def test_get_company_news_bulk_returns_dict(self):
        """get_company_news with symbols returns dict keyed by symbol."""
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool(
                "get_company_news", {"symbols": ["RELIANCE", "TCS"]}
            )
        assert not result.isError
        data = json.loads(result.content[0].text)
        assert isinstance(data, dict)
        assert "RELIANCE" in data
        assert "TCS" in data

    async def test_get_company_news_neither_param_is_error(self):
        """get_company_news with neither param returns isError."""
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool("get_company_news", {})
        assert result.isError

    async def test_get_company_news_both_params_is_error(self):
        """get_company_news with both params returns isError."""
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool(
                "get_company_news", {"symbol": "RELIANCE", "symbols": ["TCS"]}
            )
        assert result.isError

    async def test_get_morningstar_fairvalue_bulk_returns_dict(self):
        """get_morningstar_fairvalue with symbols returns dict keyed by symbol."""
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool(
                "get_morningstar_fairvalue", {"symbols": ["RELIANCE", "TCS"]}
            )
        assert not result.isError
        data = json.loads(result.content[0].text)
        assert isinstance(data, dict)
        assert "RELIANCE" in data
        assert "TCS" in data

    async def test_get_morningstar_fairvalue_bulk_values_accepted(self):
        """Bulk morningstar values may be real data or error dicts (test env)."""
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool(
                "get_morningstar_fairvalue", {"symbols": ["RELIANCE", "NOTEXIST999"]}
            )
        assert not result.isError
        data = json.loads(result.content[0].text)
        assert isinstance(data, dict)
        assert "RELIANCE" in data
        assert "NOTEXIST999" in data
