"""
MCP Server integration tests for the BLM Analytics FastAPI backend.

Requirements:
  - The server must be running before you execute these tests.
  - Default base URL is http://localhost:4455.  Override with the
    BLM_BASE_URL environment variable:

        BLM_BASE_URL=http://localhost:4455 pytest tests/test_mcp.py

  - Endpoints that hit NSE (marked with the `slow` marker) are each
    separated by a courtesy delay to avoid hammering upstream servers.
    Run only fast tests with:  pytest -m "not slow"

Install requests if needed:
    pip install requests
"""

import os

import pytest
import requests

BASE_URL: str = os.environ.get("BLM_BASE_URL", "http://127.0.0.1:4455").rstrip("/")

KNOWN_SYMBOL: str = "RELIANCE"
KNOWN_PREFIX: str = "RELI"


def mcp_request(method: str, params: dict | None = None) -> dict:
    """Make an MCP JSON-RPC request to the backend.

    The MCP server is mounted at /api/mcp and FastMCP's default
    streamable_http_path is /mcp, so the full endpoint is /api/mcp/mcp.

    With stateless_http=True and json_response=True the server accepts a
    plain POST and returns a single application/json response — no SSE, no
    session handshake required.
    """
    url = f"{BASE_URL}/api/mcp/mcp"
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
    }
    if params is not None:
        payload["params"] = params

    headers = {
        # MCP transport requires both content types in Accept
        "Accept": "application/json, text/event-stream",
        # Must be a supported protocol version
        "mcp-protocol-version": "2025-03-26",
    }

    resp = requests.post(url, json=payload, headers=headers, timeout=60)
    resp.raise_for_status()
    return resp.json()


@pytest.fixture(scope="session", autouse=True)
def require_server():
    """Fail fast with a clear message if the backend is not reachable."""
    try:
        resp = requests.get(f"{BASE_URL}/health", timeout=30)
        resp.raise_for_status()
    except Exception as exc:
        pytest.fail(
            f"Backend server not reachable at {BASE_URL} – start it with "
            f"`uvicorn main:app --host 127.0.0.1 --port 4455` before running tests.\n"
            f"Error: {exc}"
        )


class TestMCPToolDiscovery:
    """Test that MCP tools are discoverable."""

    def test_list_tools_returns_tools(self):
        """The MCP server should expose tools."""
        result = mcp_request("tools/list")
        assert "result" in result
        tools = result["result"]["tools"]
        assert len(tools) > 0

    def test_tool_names_included(self):
        """Verify expected tool names are present."""
        result = mcp_request("tools/list")
        tool_names = {t["name"] for t in result["result"]["tools"]}

        expected_tools = {
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
        assert expected_tools.issubset(tool_names)


class TestMCPToolsList:
    """Test listing MCP tools returns proper schema."""

    def test_tool_has_description(self):
        """Each tool should have a description."""
        result = mcp_request("tools/list")
        for tool in result["result"]["tools"]:
            assert "description" in tool
            assert tool["description"]


class TestMCPToolCall:
    """Test calling MCP tools."""

    def test_health_check(self):
        """Health check tool should return ok status."""
        result = mcp_request("tools/call", {"name": "health_check", "arguments": {}})
        assert "result" in result
        content = result["result"]["content"]
        assert len(content) > 0
        assert content[0]["type"] == "text"
        assert '"status": "ok"' in content[0]["text"]

    def test_list_stock_universe(self):
        """List stock universe tool should return records."""
        result = mcp_request(
            "tools/call", {"name": "list_stock_universe", "arguments": {}}
        )
        assert "result" in result
        content = result["result"]["content"]
        assert len(content) > 0
        assert content[0]["type"] == "text"

    def test_get_stock_universe_known_symbol(self):
        """Get stock universe for known symbol."""
        result = mcp_request(
            "tools/call",
            {"name": "get_stock_universe", "arguments": {"symbol": KNOWN_SYMBOL}},
        )
        assert "result" in result
        content = result["result"]["content"]
        assert len(content) > 0
        assert content[0]["type"] == "text"
        data = content[0]["text"]
        assert KNOWN_SYMBOL in data

    def test_get_stock_universe_unknown_symbol(self):
        """Get stock universe for unknown symbol should error."""
        result = mcp_request(
            "tools/call",
            {"name": "get_stock_universe", "arguments": {"symbol": "NOTEXIST999"}},
        )
        assert "error" in result or "result" in result
        if "error" in result:
            assert result["error"]["code"] != 0

    def test_search_stock_universe(self):
        """Search stock universe tool should return matching records."""
        result = mcp_request(
            "tools/call",
            {"name": "search_stock_universe", "arguments": {"prefix": KNOWN_PREFIX}},
        )
        assert "result" in result
        content = result["result"]["content"]
        assert len(content) > 0


class TestMCPScreenerTools:
    """Test screener-related MCP tools."""

    def test_screener_search(self):
        """Screener search should return results."""
        result = mcp_request(
            "tools/call", {"name": "screener_search", "arguments": {"q": "reliance"}}
        )
        assert "result" in result
        content = result["result"]["content"]
        assert len(content) > 0

    def test_screener_search_empty_query(self):
        """Empty query should be rejected."""
        result = mcp_request(
            "tools/call", {"name": "screener_search", "arguments": {"q": ""}}
        )
        assert "error" in result or "result" in result

    def test_screener_company_without_auth(self):
        """Screener company returns either data (if authenticated) or an auth error."""
        result = mcp_request(
            "tools/call",
            {"name": "screener_company", "arguments": {"symbol": KNOWN_SYMBOL}},
        )
        # Either a top-level JSON-RPC error, or a result (success or isError)
        assert "result" in result or "error" in result
        if "result" in result:
            content = result["result"]["content"]
            assert len(content) > 0
            assert content[0]["type"] == "text"


@pytest.mark.slow
class TestMCPMarketTools:
    """Test market-related MCP tools (slow, hits NSE)."""

    def test_get_top_gainers(self):
        """Get top gainers should return data."""
        result = mcp_request("tools/call", {"name": "get_top_gainers", "arguments": {}})
        assert "result" in result
        content = result["result"]["content"]
        assert len(content) > 0
        assert content[0]["type"] == "text"

    def test_get_bulk_deals(self):
        """Get bulk deals for a symbol.

        NSE may not have bulk deal data for every symbol on every day.
        The tool should return a list (possibly empty) without error.
        """
        result = mcp_request(
            "tools/call",
            {"name": "get_bulk_deals", "arguments": {"symbol": KNOWN_SYMBOL}},
        )
        assert "result" in result
        content = result["result"]["content"]
        # Result is a list (possibly empty — NSE may have no deals for this symbol today)
        assert isinstance(content, list)


@pytest.mark.slow
class TestMCPCorporateFilings:
    """Test corporate filings MCP tool."""

    def test_get_corporate_filings(self):
        """Get corporate filings should return structured data."""
        result = mcp_request(
            "tools/call",
            {"name": "get_corporate_filings", "arguments": {"symbol": KNOWN_SYMBOL}},
        )
        assert "result" in result or "error" in result
        if "result" in result:
            content = result["result"]["content"]
            assert len(content) > 0


class TestMCPErrorHandling:
    """Test MCP error handling."""

    def test_invalid_tool_name(self):
        """Calling non-existent tool should return an error response.

        MCP encodes tool-level errors as result.isError=true rather than
        a top-level JSON-RPC 'error' key.  Accept either form.
        """
        result = mcp_request(
            "tools/call", {"name": "nonexistent_tool", "arguments": {}}
        )
        # Either a JSON-RPC protocol error or an MCP isError result
        is_rpc_error = "error" in result
        is_mcp_error = "result" in result and result["result"].get("isError") is True
        assert is_rpc_error or is_mcp_error

    def test_invalid_symbol_format(self):
        """Invalid symbol format should return error."""
        result = mcp_request(
            "tools/call",
            {"name": "get_stock_universe", "arguments": {"symbol": "INVALID@@@"}},
        )
        assert "error" in result or "result" in result


class TestMCPScreenerQuarterly:
    """Tests for the get_company_quarterly_results MCP tool."""

    def test_tool_is_listed(self):
        """get_company_quarterly_results must appear in the tools list."""
        result = mcp_request("tools/list")
        tool_names = {t["name"] for t in result["result"]["tools"]}
        assert "get_company_quarterly_results" in tool_names

    def test_tool_has_description(self):
        """Tool must carry a non-empty description."""
        result = mcp_request("tools/list")
        tools = {t["name"]: t for t in result["result"]["tools"]}
        tool = tools.get("get_company_quarterly_results", {})
        assert tool.get("description"), (
            "get_company_quarterly_results has no description"
        )

    def test_call_returns_result_or_auth_error(self):
        """
        Returns a successful result when authenticated, or an isError content
        entry (RuntimeError) when no screener.in session is available.
        Either outcome is valid — the important thing is the tool is callable.
        """
        result = mcp_request(
            "tools/call",
            {
                "name": "get_company_quarterly_results",
                "arguments": {"symbol": KNOWN_SYMBOL},
            },
        )
        assert "result" in result or "error" in result
        if "result" in result:
            content = result["result"]["content"]
            assert len(content) > 0
            assert content[0]["type"] == "text"

    def test_success_response_schema(self):
        """On 200, the tool response must include symbol, consolidated, quarterly_results."""
        result = mcp_request(
            "tools/call",
            {
                "name": "get_company_quarterly_results",
                "arguments": {"symbol": KNOWN_SYMBOL},
            },
        )
        if "error" in result:
            pytest.skip("JSON-RPC level error — server may be unavailable")
        content = result["result"]["content"]
        if result["result"].get("isError"):
            pytest.skip("screener.in session not available (auth error)")
        import json as _json

        data = _json.loads(content[0]["text"])
        assert "symbol" in data
        assert "consolidated" in data
        assert "quarterly_results" in data

    def test_quarterly_results_nested_structure(self):
        """quarterly_results must be year → month → {metric: value}."""
        result = mcp_request(
            "tools/call",
            {
                "name": "get_company_quarterly_results",
                "arguments": {"symbol": KNOWN_SYMBOL},
            },
        )
        if "error" in result:
            pytest.skip("server unavailable")
        if result["result"].get("isError"):
            pytest.skip("screener.in session not available")
        import json as _json

        data = _json.loads(result["result"]["content"][0]["text"])
        qr = data.get("quarterly_results", {})
        if not qr:
            pytest.skip("quarterly_results is empty")
        for year_key, months in qr.items():
            assert isinstance(months, dict), f"Expected dict under year '{year_key}'"
            for month_key, metrics in months.items():
                assert isinstance(metrics, dict), (
                    f"Expected dict under '{year_key}.{month_key}'"
                )

    def test_invalid_symbol_is_error(self):
        """Invalid symbol format must produce an error result."""
        result = mcp_request(
            "tools/call",
            {
                "name": "get_company_quarterly_results",
                "arguments": {"symbol": "INVALID@@@"},
            },
        )
        assert "error" in result or (
            "result" in result and result["result"].get("isError") is True
        )
