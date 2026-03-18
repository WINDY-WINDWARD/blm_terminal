# BLM MCP Bundle

Claude Desktop plugin that proxies tool calls to the BLM Analytics backend.

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

## Available Tools (28)

### Market Data (12)
- `health_check` - Service health status
- `get_top_gainers` - Today's top-gaining NSE equities
- `get_top_losers` - Today's top-losing NSE equities
- `get_bulk_deals` - Bulk deals for a symbol
- `get_block_deals` - Block deals for a symbol
- `get_high_short_interest` - High short interest stocks
- `get_largedeal_snapshot` - Recent large deals snapshot
- `get_change_ranges` - Multi-timeframe % changes
- `get_symbol_data` - Live quote data (LTP, 52wk high/low, etc.)
- `get_52week_low_stocks` - New 52-week low stocks
- `get_52week_high_stocks` - New 52-week high stocks
- `get_volume_gainers` - Volume gainers

### Screener.in (4)
- `screener_search` - Search companies by name/symbol
- `screener_company` - Get fundamentals (P/E, ROCE, ROE, etc.)
- `screener_trades` - Insider trades, bulk/block deals
- `get_company_quarterly_results` - Full quarterly results

### Stock Universe (3)
- `list_stock_universe` - All stocks in DB
- `get_stock_universe` - Single stock details
- `search_stock_universe` - Search by prefix

### Watchlist (3)
- `list_watchlist` - Get all watchlist items
- `add_watchlist_item` - Add symbol to watchlist
- `remove_watchlist_item` - Remove by ID

### News (2)
- `get_global_news` - Global MoneyControl news
- `get_company_news` - Symbol-specific news

### Industries/Sectors (4)
- `list_industries` - All industries
- `list_sectors` - All sectors
- `get_industry_stocks` - Stocks in an industry
- `get_sector_stocks` - Stocks in a sector

## Cross-Platform

The build script works on:
- **Windows** (cmd, PowerShell)
- **Linux** (bash)
- **macOS** (zsh, bash)
