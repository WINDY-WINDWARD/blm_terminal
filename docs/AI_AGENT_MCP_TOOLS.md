# AI Agent MCP Tools Documentation

This document outlines the tools available to AI agents operating within the BLM Terminal ecosystem. These tools are available both through the `blm-mcp-bundle` (Claude Desktop MCP plugin) and the internal AI chat agent (`backend/app/routers/ai_chat.py`).

## Core Market Data

### `get_symbol_data`
Fetch live NSE quote data for a symbol, including LTP, 52-week range, sector, and industry.

### `get_change_ranges`
Fetch NSE percentage price changes across multiple timeframes (1d to 5y) for a symbol.

### `get_top_gainers` / `get_top_losers`
Fetch today's top-gaining or top-losing NSE equities ranked by intraday percentage change. Supports optional category filter: NIFTY, BANKNIFTY, NIFTYNEXT50, SecGtr20, SecLwr20, FOSec, allSec (default).

### `get_volume_gainers`
Fetch NSE stocks with the largest volume surge relative to their weekly average.

### `get_52week_low_stocks` / `get_52week_high_stocks`
Fetch NSE stocks that crossed a new 52-week low or high today.

### `list_industries` / `list_sectors`
List all NSE industries or sectors with market cap, PE ratio, advance/decline counts, and sentiment.

### `get_industry_stocks` / `get_sector_stocks`
Fetch all NSE stocks in a given industry or sector by slug, sorted by market cap descending.

## Deals & Short Interest

### `get_bulk_deals` / `get_block_deals`
Fetch recent NSE bulk or block deal records for a given stock symbol.

### `get_largedeal_snapshot`
Fetch a combined real-time snapshot of NSE insider, bulk, and block deals across all stocks.

### `get_high_short_interest`
Fetch today's NSE stocks flagged for high short-selling interest.

## Stock Universe & Screening

### `list_stock_universe` / `get_stock_universe` / `search_stock_universe`
Look up, list, or search the tracked NSE stock universe metadata (symbol, company name, sector, industry, PE).

### `company_fdm`
Fetch comprehensive FDM widget data (screener fundamentals, tradingview stats, morningstar fair value, DCF valuation, NSE ratios, corporate events) for an NSE company in a single call. Accepts a `sections` filter to limit data context and prevent context bloat.

### `screener_search` / `screener_trades` / `get_company_quarterly_results`
Search screener.in, fetch insider trades, and deal records for an NSE company.

### `run_tql_screener`
Run a custom TQL (Ticker Query Language) screener query against all NSE stocks. Supports complex logic (AND/OR/NOT) with indicators (RSI, ATR, MACD, etc.), fundamentals (PE, Volume), and intervals (1h, W, M).

## Watchlists & Portfolio

### `list_watchlists` / `create_watchlist`
List user-created watchlists or create a new one.

### `list_watchlist` / `get_watchlist_items` / `get_watchlist_symbols`
Fetch items or symbols from the default watchlist (ID 1) or a specific watchlist ID.

### `add_watchlist_item` / `remove_watchlist_item` / `bulk_replace_watchlist`
Add, remove, or atomically replace items in a watchlist.

### `optimize_portfolio`
Run portfolio optimization on a list of NSE symbols using mean-variance or hierarchical risk parity. Returns portfolio weights, expected annual return/volatility/Sharpe, correlation matrix, and per-symbol stats.

## News & Notifications

### `get_global_news` / `get_company_news`
Fetch recent financial news globally or for a specific NSE company. Includes NLP sentiment analysis, threat classification, and entity extraction. `get_company_news` automatically uses `iinvest` as its primary and most reliable source.

### `get_global_notifications` / `get_notifications`
Fetch unread global NSE scan alerts or market-event notifications for a watchlist.

### `get_upcoming_events` / `get_recent_announcements`
Fetch upcoming corporate events or recent announcements for a stock.

## Valuation

### `get_morningstar_fairvalue`
Fetch Morningstar fair value estimate and uncertainty rating for an NSE stock symbol.

## iinvest (Corporate Data)
*Note: Auth is automatic for all iinvest endpoints. NLP sentiment and threat classification are computed locally.*

### `iinvest_all`
Fetch all 18 iinvest data endpoints in parallel (error-tolerant per section) for a single NSE company.

### `iinvest_overview` / `iinvest_path`
Fetch the iinvest overview HTML page for identity fields, or resolve a symbol to its iinvest path slug.

### Specific iinvest Endpoints:
- `iinvest_announcements`: Corporate announcements (with PDF links).
- `iinvest_auditors`: Statutory auditors and appointment dates.
- `iinvest_board_meetings`: Board meeting purposes and dates (with PDF links).
- `iinvest_block_deals`: Block deal records (today + historical).
- `iinvest_capital_history`: Capital issuance history.
- `iinvest_corporate_actions`: Corporate actions (Dividend | Split | Bonus | Others).
- `iinvest_financial_peers` / `iinvest_financial_peer_filters`: Peer comparison ratios and filters.
- `iinvest_index_of_charges`: MCA index of charges.
- `iinvest_insider_trading`: Insider trading records.
- `iinvest_key_shareholders`: Quarterly shareholding pattern (Promoter/FII/DII/Public over ~5y).
- `iinvest_legal_cases` / `iinvest_tribunals`: Civil/criminal legal cases and NCLT/SEBI tribunal cases.
- `iinvest_marketdata_timeseries`: OHLC timeseries (1D/1W/1M/3M/6M/1Y) with 52-week high/low and volume.
- `iinvest_pledged_shares`: Promoter pledged shares.
- `iinvest_sast`: SAST (Substantial Acquisition of Shares & Takeovers) disclosures.

## User-Uploaded Documents (PDF & CSV)

Documents uploaded through the AI chat (paperclip / drag-and-drop) live in a
per-user library and stay available after a chat session is deleted. CSV files
are materialised as one read-only SQLite table per document (`csv_doc_<id>`);
PDFs are stored page-by-page and indexed in SQLite FTS5 (`pdf_pages_fts`).
Every tool below is ownership-checked against the authenticated user.

### `query_csv`
Run a single read-only `SELECT` against one uploaded CSV. `PRAGMA query_only=ON`
plus a SQLite authorizer restrict access to the document's own table, so writes,
`PRAGMA`, `ATTACH`, and cross-table reads are rejected. Results are capped at 50
rows (`truncated` flags the cut-off).

### `describe_csv`
Return the schema (column names/types), row count, per-column null counts,
numeric min/avg/max, and the top 10 categorical values. Pass `column` for a
single-column deep dive.

### `search_pdf`
Full-text search over an uploaded PDF's pages. Returns the best-matching pages
with BM25 ranking and a highlighted snippet.

### `read_pdf_pages`
Return the exact text of a page range (max 5 pages and 20,000 characters per
call).

### `get_pdf_outline`
Return the PDF's flattened bookmark outline as `(depth, title, page_number)`
entries.

## System

### `health_check`
Check backend service health and connectivity.
