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
