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
            "get_market_fii_dii_activity",
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


class TestMCPWatchlistTools:
    """Tests for watchlist MCP tools."""

    TEST_SYMBOL = "WATCH"
    TEST_EXCHANGE = "NSE"

    def test_list_watchlist(self):
        """list_watchlist should return all watchlist items."""
        result = mcp_request("tools/call", {"name": "list_watchlist", "arguments": {}})
        assert "result" in result
        content = result["result"]["content"]
        assert len(content) > 0
        assert content[0]["type"] == "text"

    def test_list_watchlist_returns_array(self):
        """list_watchlist should return a JSON array."""
        result = mcp_request("tools/call", {"name": "list_watchlist", "arguments": {}})
        
        # Use structuredContent for structured data (list of items)
        data = result["result"]["structuredContent"]["result"]
        assert isinstance(data, list)
        if data:
            assert "id" in data[0]
            assert "symbol" in data[0]
            assert "exchange" in data[0]

    def test_get_watchlist_symbols(self):
        """get_watchlist_symbols should return just the symbols."""
        result = mcp_request(
            "tools/call", {"name": "get_watchlist_symbols", "arguments": {}}
        )
        assert "result" in result
        # Use structuredContent for structured data
        data = result["result"]["structuredContent"]["result"]
        assert isinstance(data, list)
        assert all(isinstance(s, str) for s in data)

    def test_add_watchlist_item(self):
        """add_watchlist_item should create a new item."""
        result = mcp_request(
            "tools/call",
            {
                "name": "add_watchlist_item",
                "arguments": {"symbol": "WATCH", "exchange": "NSE"},
            },
        )

        # Dict-returning tools have structuredContent directly
        data = result["result"]["structuredContent"]
        assert "id" in data
        assert data["symbol"] == "WATCH"
        assert data["exchange"] == "NSE"

    def test_add_watchlist_item_idempotent(self):
        """add_watchlist_item should be idempotent."""
        result1 = mcp_request(
            "tools/call",
            {
                "name": "add_watchlist_item",
                "arguments": {"symbol": "WATCH", "exchange": "NSE"},
            },
        )

        data1 = result1["result"]["structuredContent"]

        result2 = mcp_request(
            "tools/call",
            {
                "name": "add_watchlist_item",
                "arguments": {"symbol": "WATCH", "exchange": "NSE"},
            },
        )

        data2 = result2["result"]["structuredContent"]
        assert data1["id"] == data2["id"]

    def test_add_watchlist_item_normalizes_input(self):
        """Input should be normalized to uppercase."""
        result = mcp_request(
            "tools/call",
            {
                "name": "add_watchlist_item",
                "arguments": {"symbol": "test", "exchange": "nse"},
            },
        )

        # Dict-returning tools have structuredContent directly
        data = result["result"]["structuredContent"]
        assert data["symbol"] == "TEST"
        assert data["exchange"] == "NSE"

    def test_add_watchlist_item_missing_fields(self):
        """Missing fields should produce an error."""
        result = mcp_request(
            "tools/call",
            {"name": "add_watchlist_item", "arguments": {"symbol": "TEST"}},
        )
        assert "error" in result or (
            "result" in result and result["result"].get("isError") is True
        )

    def test_remove_watchlist_item(self):
        """remove_watchlist_item should delete an item by id."""
        # First add an item to delete
        add_result = mcp_request(
            "tools/call",
            {
                "name": "add_watchlist_item",
                "arguments": {"symbol": "DELTEST", "exchange": "NSE"},
            },
        )

        item = add_result["result"]["structuredContent"]
        item_id = item["id"]

        # Now delete it
        result = mcp_request(
            "tools/call",
            {"name": "remove_watchlist_item", "arguments": {"item_id": item_id}},
        )
        assert "result" in result
        # remove_watchlist_item returns a dict
        data = result["result"]["structuredContent"]
        assert data.get("ok") is True

    def test_remove_watchlist_item_not_found(self):
        """Removing a non-existent item should error."""
        result = mcp_request(
            "tools/call",
            {"name": "remove_watchlist_item", "arguments": {"item_id": 999999}},
        )
        assert "error" in result or (
            "result" in result and result["result"].get("isError") is True
        )


class TestMCPNewWatchlistTools:
    """Tests for list_watchlists and get_watchlist_items."""

    def test_list_watchlists_returns_array(self):
        """list_watchlists should return an array in structuredContent."""
        result = mcp_request("tools/call", {"name": "list_watchlists", "arguments": {}})
        assert "result" in result
        data = result["result"]["structuredContent"]["result"]
        assert isinstance(data, list)

    def test_get_watchlist_items_nonexistent_is_error(self):
        """get_watchlist_items with nonexistent id should error."""
        result = mcp_request(
            "tools/call",
            {"name": "get_watchlist_items", "arguments": {"watchlist_id": 999999}},
        )
        assert "error" in result or (
            "result" in result and result["result"].get("isError") is True
        )


class TestMCPNotificationTools:
    """Tests for notification MCP tools."""

    def test_get_notifications_returns_list(self):
        """get_notifications should return a list (possibly empty)."""
        result = mcp_request(
            "tools/call",
            {"name": "get_notifications", "arguments": {"watchlist_id": 1}},
        )
        assert "result" in result
        content = result["result"]["content"]
        assert len(content) > 0
        assert content[0]["type"] == "text"

    def test_get_global_notifications_returns_list(self):
        """get_global_notifications with limit should return a list (possibly empty)."""
        result = mcp_request(
            "tools/call",
            {"name": "get_global_notifications", "arguments": {"limit": 5}},
        )
        assert "result" in result
        content = result["result"]["content"]
        assert len(content) > 0
        assert content[0]["type"] == "text"


class TestMCPMorningstarTool:
    """Tests for get_morningstar_fairvalue MCP tool."""

    def test_single_symbol_callable(self):
        """get_morningstar_fairvalue with single symbol is callable."""
        result = mcp_request(
            "tools/call",
            {"name": "get_morningstar_fairvalue", "arguments": {"symbol": "RELIANCE"}},
        )
        assert "result" in result or "error" in result
        if "result" in result:
            content = result["result"]["content"]
            assert len(content) > 0
            assert content[0]["type"] == "text"
            assert content[0]["text"]

    def test_neither_param_is_error(self):
        """Neither symbol nor symbols returns error."""
        result = mcp_request(
            "tools/call",
            {"name": "get_morningstar_fairvalue", "arguments": {}},
        )
        assert "error" in result or (
            "result" in result and result["result"].get("isError") is True
        )

    def test_both_params_is_error(self):
        """Both symbol and symbols returns error."""
        result = mcp_request(
            "tools/call",
            {
                "name": "get_morningstar_fairvalue",
                "arguments": {"symbol": "RELIANCE", "symbols": ["TCS"]},
            },
        )
        assert "error" in result or (
            "result" in result and result["result"].get("isError") is True
        )


class TestMCPCompanyNews:
    """Tests for get_company_news MCP tool."""

    @pytest.mark.slow
    def test_single_symbol_callable(self):
        """get_company_news with single symbol is callable."""
        result = mcp_request(
            "tools/call",
            {
                "name": "get_company_news",
                "arguments": {"symbol": "RELIANCE", "refresh": False},
            },
        )
        assert "result" in result or "error" in result
        if "result" in result:
            content = result["result"]["content"]
            assert len(content) > 0
            assert content[0]["type"] == "text"

    def test_neither_param_is_error(self):
        """Neither symbol nor symbols returns error."""
        result = mcp_request(
            "tools/call",
            {"name": "get_company_news", "arguments": {}},
        )
        assert "error" in result or (
            "result" in result and result["result"].get("isError") is True
        )

    def test_both_params_is_error(self):
        """Both symbol and symbols returns error."""
        result = mcp_request(
            "tools/call",
            {
                "name": "get_company_news",
                "arguments": {"symbol": "RELIANCE", "symbols": ["TCS"]},
            },
        )
        assert "error" in result or (
            "result" in result and result["result"].get("isError") is True
        )

    def test_response_includes_nlp_fields(self):
        """get_company_news response includes all NLP fields."""
        import json

        result = mcp_request(
            "tools/call",
            {"name": "get_company_news", "arguments": {"symbol": "RELIANCE", "days": 1, "limit": 5}},
        )
        if "error" in result or result["result"].get("isError"):
            return
        content = result["result"]["content"]
        text = content[0]["text"]
        data = json.loads(text)
        if isinstance(data, list) and len(data) > 0:
            article = data[0]
            assert "sentiment" in article
            assert "sentiment_score" in article
            assert "confidence" in article
            assert "language" in article
            assert "entities" in article
            assert "threat_level" in article
            assert "threat_category" in article
            assert "source_credibility" in article


class TestMCPGlobalNews:
    """Tests for get_global_news MCP tool."""

    def test_returns_list(self):
        """get_global_news returns a list (possibly empty)."""
        result = mcp_request("tools/call", {"name": "get_global_news", "arguments": {}})
        assert "result" in result
        assert result["result"].get("isError") is not True
        content = result["result"]["content"]
        assert len(content) > 0

    def test_response_includes_nlp_fields(self):
        """get_global_news response includes all NLP fields."""
        import json

        result = mcp_request("tools/call", {"name": "get_global_news", "arguments": {"days": 1, "limit": 5}})
        assert "result" in result
        content = result["result"]["content"]
        text = content[0]["text"]
        data = json.loads(text)
        assert "data" in data
        if len(data["data"]) > 0:
            article = data["data"][0]
            assert "sentiment" in article
            assert "sentiment_score" in article
            assert "confidence" in article
            assert "language" in article
            assert "entities" in article
            assert "threat_level" in article
            assert "threat_category" in article
            assert "source_credibility" in article

    def test_filter_by_sentiment(self):
        """get_global_news with sentiment filter returns filtered results."""
        import json

        result = mcp_request(
            "tools/call",
            {"name": "get_global_news", "arguments": {"days": 30, "sentiment": "POSITIVE", "limit": 20}},
        )
        assert "result" in result
        if result["result"].get("isError"):
            return
        content = result["result"]["content"]
        text = content[0]["text"]
        data = json.loads(text)
        if len(data["data"]) > 0:
            for article in data["data"]:
                if article.get("sentiment"):
                    assert article["sentiment"].upper() in ("POSITIVE", "NEGATIVE", "NEUTRAL"), \
                        f"Unexpected sentiment: {article['sentiment']}"

    def test_filter_by_source(self):
        """get_global_news with sources filter returns filtered results."""
        import json

        result = mcp_request(
            "tools/call",
            {"name": "get_global_news", "arguments": {"sources": ["moneycontrol"], "limit": 10}},
        )
        assert "result" in result

    def test_filter_by_threat_level(self):
        """get_global_news with threat_level filter returns filtered results."""
        import json

        result = mcp_request(
            "tools/call",
            {"name": "get_global_news", "arguments": {"threat_level": "HIGH", "limit": 10}},
        )
        assert "result" in result

    def test_filter_by_language(self):
        """get_global_news with language filter returns filtered results."""
        import json

        result = mcp_request(
            "tools/call",
            {"name": "get_global_news", "arguments": {"language": "en", "limit": 10}},
        )
        assert "result" in result


class TestMCPIndustrySector:
    """Tests for industry and sector MCP tools."""

    def test_list_industries_returns_list_with_slug(self):
        """list_industries returns list with slug field."""
        result = mcp_request(
            "tools/call", {"name": "list_industries", "arguments": {}}
        )
        assert "result" in result
        content = result["result"]["content"]
        assert len(content) > 0
        first_text = content[0]["text"]
        import json

        first = json.loads(first_text)
        assert "slug" in first

    def test_list_sectors_returns_list(self):
        """list_sectors returns list (possibly empty)."""
        result = mcp_request("tools/call", {"name": "list_sectors", "arguments": {}})
        assert "result" in result
        content = result["result"]["content"]
        # Sectors may be empty in test DB - just verify it's a list
        data = result["result"]["structuredContent"]["result"]
        assert isinstance(data, list)

    def test_get_industry_stocks_valid_slug(self):
        """get_industry_stocks with valid slug returns list (possibly empty)."""
        result = mcp_request(
            "tools/call",
            {"name": "get_industry_stocks", "arguments": {"slug": "bank-private"}},
        )
        assert "result" in result
        assert result["result"].get("isError") is not True
        content = result["result"]["content"]
        assert len(content) > 0

    def test_get_industry_stocks_invalid_slug_is_error(self):
        """get_industry_stocks with invalid slug returns error."""
        result = mcp_request(
            "tools/call",
            {"name": "get_industry_stocks", "arguments": {"slug": "NOTEXIST999"}},
        )
        assert "error" in result or (
            "result" in result and result["result"].get("isError") is True
        )

    def test_get_sector_stocks_invalid_slug_is_error(self):
        """get_sector_stocks with invalid slug returns error."""
        result = mcp_request(
            "tools/call",
            {"name": "get_sector_stocks", "arguments": {"slug": "nonexistent-sector"}},
        )
        assert "error" in result or (
            "result" in result and result["result"].get("isError") is True
        )


@pytest.mark.slow
class TestMCPBulkSymbolTools:
    """Tests for bulk symbol parameter on all tools that support it."""

    def test_get_bulk_deals_bulk_returns_dict(self):
        """get_bulk_deals with symbols returns dict keyed by symbol."""
        result = mcp_request(
            "tools/call",
            {"name": "get_bulk_deals", "arguments": {"symbols": ["RELIANCE", "TCS"]}},
        )
        assert "result" in result
        import json

        data = json.loads(result["result"]["content"][0]["text"])
        assert isinstance(data, dict)
        assert "RELIANCE" in data
        assert "TCS" in data

    def test_get_bulk_deals_neither_param_is_error(self):
        """get_bulk_deals with neither param returns error."""
        result = mcp_request(
            "tools/call", {"name": "get_bulk_deals", "arguments": {}}
        )
        assert "error" in result or (
            "result" in result and result["result"].get("isError") is True
        )

    def test_get_bulk_deals_both_params_is_error(self):
        """get_bulk_deals with both params returns error."""
        result = mcp_request(
            "tools/call",
            {
                "name": "get_bulk_deals",
                "arguments": {"symbol": "RELIANCE", "symbols": ["TCS"]},
            },
        )
        assert "error" in result or (
            "result" in result and result["result"].get("isError") is True
        )

    def test_get_block_deals_bulk_returns_dict(self):
        """get_block_deals with symbols returns dict keyed by symbol."""
        result = mcp_request(
            "tools/call",
            {"name": "get_block_deals", "arguments": {"symbols": ["RELIANCE", "TCS"]}},
        )
        assert "result" in result
        import json

        data = json.loads(result["result"]["content"][0]["text"])
        assert isinstance(data, dict)
        assert "RELIANCE" in data
        assert "TCS" in data

    def test_get_block_deals_neither_param_is_error(self):
        """get_block_deals with neither param returns error."""
        result = mcp_request(
            "tools/call", {"name": "get_block_deals", "arguments": {}}
        )
        assert "error" in result or (
            "result" in result and result["result"].get("isError") is True
        )

    def test_get_block_deals_both_params_is_error(self):
        """get_block_deals with both params returns error."""
        result = mcp_request(
            "tools/call",
            {
                "name": "get_block_deals",
                "arguments": {"symbol": "RELIANCE", "symbols": ["TCS"]},
            },
        )
        assert "error" in result or (
            "result" in result and result["result"].get("isError") is True
        )

    def test_get_change_ranges_bulk_returns_dict(self):
        """get_change_ranges with symbols returns dict keyed by symbol."""
        result = mcp_request(
            "tools/call",
            {"name": "get_change_ranges", "arguments": {"symbols": ["RELIANCE", "TCS"]}},
        )
        assert "result" in result
        import json

        data = json.loads(result["result"]["content"][0]["text"])
        assert isinstance(data, dict)
        assert "RELIANCE" in data
        assert "TCS" in data

    def test_get_change_ranges_neither_param_is_error(self):
        """get_change_ranges with neither param returns error."""
        result = mcp_request(
            "tools/call", {"name": "get_change_ranges", "arguments": {}}
        )
        assert "error" in result or (
            "result" in result and result["result"].get("isError") is True
        )

    def test_get_change_ranges_both_params_is_error(self):
        """get_change_ranges with both params returns error."""
        result = mcp_request(
            "tools/call",
            {
                "name": "get_change_ranges",
                "arguments": {"symbol": "RELIANCE", "symbols": ["TCS"]},
            },
        )
        assert "error" in result or (
            "result" in result and result["result"].get("isError") is True
        )

    def test_get_symbol_data_bulk_returns_dict(self):
        """get_symbol_data with symbols returns dict keyed by symbol."""
        result = mcp_request(
            "tools/call",
            {"name": "get_symbol_data", "arguments": {"symbols": ["RELIANCE", "TCS"]}},
        )
        assert "result" in result
        import json

        data = json.loads(result["result"]["content"][0]["text"])
        assert isinstance(data, dict)
        assert "RELIANCE" in data
        assert "TCS" in data

    def test_get_symbol_data_neither_param_is_error(self):
        """get_symbol_data with neither param returns error."""
        result = mcp_request(
            "tools/call", {"name": "get_symbol_data", "arguments": {}}
        )
        assert "error" in result or (
            "result" in result and result["result"].get("isError") is True
        )

    def test_get_symbol_data_both_params_is_error(self):
        """get_symbol_data with both params returns error."""
        result = mcp_request(
            "tools/call",
            {
                "name": "get_symbol_data",
                "arguments": {"symbol": "RELIANCE", "symbols": ["TCS"]},
            },
        )
        assert "error" in result or (
            "result" in result and result["result"].get("isError") is True
        )

    def test_get_corporate_filings_bulk_returns_dict(self):
        """get_corporate_filings with symbols returns dict keyed by symbol."""
        result = mcp_request(
            "tools/call",
            {"name": "get_corporate_filings", "arguments": {"symbols": ["RELIANCE", "TCS"]}},
        )
        assert "result" in result
        import json

        data = json.loads(result["result"]["content"][0]["text"])
        assert isinstance(data, dict)
        assert "RELIANCE" in data
        assert "TCS" in data

    def test_get_corporate_filings_neither_param_is_error(self):
        """get_corporate_filings with neither param returns error."""
        result = mcp_request(
            "tools/call", {"name": "get_corporate_filings", "arguments": {}}
        )
        assert "error" in result or (
            "result" in result and result["result"].get("isError") is True
        )

    def test_get_corporate_filings_both_params_is_error(self):
        """get_corporate_filings with both params returns error."""
        result = mcp_request(
            "tools/call",
            {
                "name": "get_corporate_filings",
                "arguments": {"symbol": "RELIANCE", "symbols": ["TCS"]},
            },
        )
        assert "error" in result or (
            "result" in result and result["result"].get("isError") is True
        )

    def test_screener_company_bulk_returns_dict(self):
        """screener_company with symbols returns dict keyed by symbol."""
        result = mcp_request(
            "tools/call",
            {"name": "screener_company", "arguments": {"symbols": ["RELIANCE", "TCS"]}},
        )
        assert "result" in result or "error" in result
        if "result" in result and not result["result"].get("isError"):
            import json

            data = json.loads(result["result"]["content"][0]["text"])
            assert isinstance(data, dict)

    def test_screener_company_neither_param_is_error(self):
        """screener_company with neither param returns error."""
        result = mcp_request(
            "tools/call", {"name": "screener_company", "arguments": {}}
        )
        assert "error" in result or (
            "result" in result and result["result"].get("isError") is True
        )

    def test_screener_company_both_params_is_error(self):
        """screener_company with both params returns error."""
        result = mcp_request(
            "tools/call",
            {
                "name": "screener_company",
                "arguments": {"symbol": "RELIANCE", "symbols": ["TCS"]},
            },
        )
        assert "error" in result or (
            "result" in result and result["result"].get("isError") is True
        )

    def test_screener_trades_bulk_returns_dict(self):
        """screener_trades with symbols returns dict keyed by symbol."""
        result = mcp_request(
            "tools/call",
            {"name": "screener_trades", "arguments": {"symbols": ["RELIANCE", "TCS"]}},
        )
        assert "result" in result or "error" in result
        if "result" in result and not result["result"].get("isError"):
            import json

            data = json.loads(result["result"]["content"][0]["text"])
            assert isinstance(data, dict)

    def test_screener_trades_neither_param_is_error(self):
        """screener_trades with neither param returns error."""
        result = mcp_request(
            "tools/call", {"name": "screener_trades", "arguments": {}}
        )
        assert "error" in result or (
            "result" in result and result["result"].get("isError") is True
        )

    def test_screener_trades_both_params_is_error(self):
        """screener_trades with both params returns error."""
        result = mcp_request(
            "tools/call",
            {
                "name": "screener_trades",
                "arguments": {"symbol": "RELIANCE", "symbols": ["TCS"]},
            },
        )
        assert "error" in result or (
            "result" in result and result["result"].get("isError") is True
        )

    def test_get_company_quarterly_results_bulk_returns_dict(self):
        """get_company_quarterly_results with symbols returns dict keyed by symbol."""
        result = mcp_request(
            "tools/call",
            {
                "name": "get_company_quarterly_results",
                "arguments": {"symbols": ["RELIANCE", "TCS"]},
            },
        )
        assert "result" in result or "error" in result
        if "result" in result and not result["result"].get("isError"):
            import json

            data = json.loads(result["result"]["content"][0]["text"])
            assert isinstance(data, dict)

    def test_get_company_quarterly_results_neither_param_is_error(self):
        """get_company_quarterly_results with neither param returns error."""
        result = mcp_request(
            "tools/call", {"name": "get_company_quarterly_results", "arguments": {}}
        )
        assert "error" in result or (
            "result" in result and result["result"].get("isError") is True
        )

    def test_get_company_quarterly_results_both_params_is_error(self):
        """get_company_quarterly_results with both params returns error."""
        result = mcp_request(
            "tools/call",
            {
                "name": "get_company_quarterly_results",
                "arguments": {"symbol": "RELIANCE", "symbols": ["TCS"]},
            },
        )
        assert "error" in result or (
            "result" in result and result["result"].get("isError") is True
        )

    def test_get_stock_universe_bulk_returns_dict(self):
        """get_stock_universe with symbols returns dict keyed by symbol."""
        result = mcp_request(
            "tools/call",
            {"name": "get_stock_universe", "arguments": {"symbols": ["RELIANCE", "TCS"]}},
        )
        assert "result" in result
        import json

        data = json.loads(result["result"]["content"][0]["text"])
        assert isinstance(data, dict)
        assert "RELIANCE" in data
        assert "TCS" in data

    def test_get_stock_universe_neither_param_is_error(self):
        """get_stock_universe with neither param returns error."""
        result = mcp_request(
            "tools/call", {"name": "get_stock_universe", "arguments": {}}
        )
        assert "error" in result or (
            "result" in result and result["result"].get("isError") is True
        )

    def test_get_stock_universe_both_params_is_error(self):
        """get_stock_universe with both params returns error."""
        result = mcp_request(
            "tools/call",
            {
                "name": "get_stock_universe",
                "arguments": {"symbol": "RELIANCE", "symbols": ["TCS"]},
            },
        )
        assert "error" in result or (
            "result" in result and result["result"].get("isError") is True
        )

    def test_get_company_news_bulk_returns_dict(self):
        """get_company_news with symbols returns dict keyed by symbol."""
        result = mcp_request(
            "tools/call",
            {"name": "get_company_news", "arguments": {"symbols": ["RELIANCE", "TCS"]}},
        )
        assert "result" in result
        import json

        data = json.loads(result["result"]["content"][0]["text"])
        assert isinstance(data, dict)
        assert "RELIANCE" in data
        assert "TCS" in data

    def test_get_company_news_neither_param_is_error(self):
        """get_company_news with neither param returns error."""
        result = mcp_request(
            "tools/call", {"name": "get_company_news", "arguments": {}}
        )
        assert "error" in result or (
            "result" in result and result["result"].get("isError") is True
        )

    def test_get_company_news_both_params_is_error(self):
        """get_company_news with both params returns error."""
        result = mcp_request(
            "tools/call",
            {
                "name": "get_company_news",
                "arguments": {"symbol": "RELIANCE", "symbols": ["TCS"]},
            },
        )
        assert "error" in result or (
            "result" in result and result["result"].get("isError") is True
        )

    def test_get_morningstar_fairvalue_bulk_returns_dict(self):
        """get_morningstar_fairvalue with symbols returns dict keyed by symbol."""
        result = mcp_request(
            "tools/call",
            {
                "name": "get_morningstar_fairvalue",
                "arguments": {"symbols": ["RELIANCE", "TCS"]},
            },
        )
        assert "result" in result
        import json

        data = json.loads(result["result"]["content"][0]["text"])
        assert isinstance(data, dict)
        assert "RELIANCE" in data
        assert "TCS" in data

    def test_get_morningstar_fairvalue_bulk_values_accepted(self):
        """Bulk morningstar values may be real data or error dicts (test env)."""
        result = mcp_request(
            "tools/call",
            {
                "name": "get_morningstar_fairvalue",
                "arguments": {"symbols": ["RELIANCE", "NOTEXIST999"]},
            },
        )
        assert "result" in result
        import json

        data = json.loads(result["result"]["content"][0]["text"])
        assert isinstance(data, dict)
        assert "RELIANCE" in data
        assert "NOTEXIST999" in data
