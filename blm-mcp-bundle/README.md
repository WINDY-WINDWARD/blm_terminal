# BLM MCP Bundle

Claude Desktop plugin that proxies tool calls to the BLM Analytics backend, including portfolio optimization and watchlist save actions.

## Prerequisites

1. **Node.js** (v14 or higher)
2. **mcpb CLI**: `npm install -g @anthropic-ai/mcpb`
3. **Backend server** running with MCP enabled (default port: 4455)

## Quick Start

```bash
# Install mcpb CLI
npm install -g @anthropic-ai/mcpb

# Build the bundle (defaults to localhost:4455)
cd blm-mcp-bundle
node build.js

# Or specify a different port
node build.js --port 8000

# Or use full URL from environment
PYTHON_BACKEND_URL=http://192.168.1.100:4455 node build.js
```

## Output

Creates `blm-mcp-proxy.mcpb` in the `blm-mcp-bundle/` directory.

## Installation

### Option 1: MCP Bundle (Recommended)

1. Open Claude Desktop
2. Go to **Developer → Extensions → Install Extension**
3. Select the generated `.mcpb` file
4. Enter the backend host/port in the settings UI
5. Enable the extension

### Option 2: Manual Config (Windows Workaround)

If the MCP bundle extension doesn't work due to a Claude Desktop bug on Windows, you can configure the MCP server manually in the Claude Desktop config file.

**Location:**
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Linux: `~/.config/Claude/claude_desktop_config.json`

**Steps:**

1. Open the config file in a text editor
2. Add the `mcpServers` section (merge with existing content if present):

```json
{
  "mcpServers": {
    "blm-mcp-proxy": {
      "command": "node",
      "args": ["D:\\500GB\\p1\\Projects\\blm_terminal\\blm-mcp-bundle\\server\\index.js"],
      "env": {
        "REMOTE_HOST": "192.168.1.68",
        "REMOTE_PORT": "4455",
        "REMOTE_PATH": "/api/mcp/mcp"
      }
    }
  }
}
```

**Important notes for Windows:**
- Use double backslashes (`\\`) in file paths
- The `REMOTE_PATH` must be `/api/mcp/mcp` (FastMCP's default `/mcp` nested under `/api/mcp`)
- Restart Claude Desktop after editing the config

## Available Tools (37)

### Market Data (11)
- `health_check` - Service health status
- `get_top_gainers` - Today's top-gaining NSE equities
- `get_top_losers` - Today's top-losing NSE equities
- `get_bulk_deals` - Bulk deals for one or multiple symbols
- `get_block_deals` - Block deals for one or multiple symbols
- `get_largedeal_snapshot` - Recent large deals snapshot (bulk/short/block)
- `get_change_ranges` - Multi-timeframe % changes
- `get_symbol_data` - Live quote data (LTP, 52wk high/low, etc.)
- `get_52week_low_stocks` - New 52-week low stocks
- `get_52week_high_stocks` - New 52-week high stocks
- `get_volume_gainers` - Volume gainers

### Corporate Data (2)
- `get_high_short_interest` - Stocks flagged for high short-selling interest
- `get_company_quarterly_results` - Quarterly financial results as pipe-delimited CSV

### Screener.in (3)
- `screener_search` - Search companies by name/symbol
- `screener_company` - Get fundamentals (P/E, ROCE, ROE, etc.)
- `screener_trades` - Insider trades, bulk/block deals

### Morningstar (1)
- `get_morningstar_fairvalue` - Fair value estimate for one or multiple symbols

### Stock Universe (3)
- `list_stock_universe` - All stocks in DB
- `get_stock_universe` - Single or bulk stock details
- `search_stock_universe` - Search by prefix

### Portfolio (4)
- `optimize_portfolio` - Optimize a portfolio and return weights, risk, and correlation stats
- `create_watchlist` - Create a new watchlist for saving results
- `add_watchlist_item` - Add one symbol to a watchlist
- `bulk_replace_watchlist` - Replace a watchlist with a new optimized symbol set

### Watchlist (5)
- `list_watchlist` - Get all default watchlist items
- `get_watchlist_symbols` - Distinct symbols from default watchlist
- `remove_watchlist_item` - Remove item by ID
- `list_watchlists` - List all user-created watchlists
- `get_watchlist_items` - All items in a specific watchlist

### Notifications (2)
- `get_notifications` - Unread alerts for a watchlist
- `get_global_notifications` - Global NSE scan alerts across all stocks

### News (2)
- `get_global_news` - Global news from MoneyControl and RSS sources
- `get_company_news` - Symbol-specific news with NLP analysis

### Industries/Sectors (4)
- `list_industries` - All industries with market cap, PE, sentiment
- `list_sectors` - All sectors with market cap, PE, sentiment
- `get_industry_stocks` - Stocks in an industry
- `get_sector_stocks` - Stocks in a sector

## Cross-Platform

The build script works on:
- **Windows** (cmd, PowerShell)
- **Linux** (bash)
- **macOS** (zsh, bash)
