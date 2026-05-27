# BLM Terminal

![Next.js](https://img.shields.io/badge/Next.js-16-black?logo=next.js)
![React](https://img.shields.io/badge/React-19-61DAFB?logo=react)
![Python](https://img.shields.io/badge/Python-3.11%2B-blue?logo=python)
![License](https://img.shields.io/badge/license-MIT-blue)

**A self-hosted financial terminal for NSE India** — real-time quotes, candlestick charts, order entry, positions, market analytics, fundamentals, news, and a persistent data warehouse, all in a single browser tab.

---

## Table of Contents

- [Overview](#overview)
- [Key Features](#key-features)
- [Architecture](#architecture)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Development](#development)
- [Project Structure](#project-structure)

---

## Overview

BLM Terminal is a full-stack trading dashboard built for NSE India. The frontend is a Next.js 16 App Router application that proxies all broker calls server-side via [OpenAlgo](https://github.com/marketcalls/openalgo), keeping API credentials out of the browser. A companion FastAPI service (`backend/`) independently fetches and archives NSE market data, corporate filings, screener fundamentals, MoneyControl news, and Morningstar fair values into a local SQLite database — acting as a standalone analytics data warehouse and MCP server.

---

## Key Features

| Area | Detail |
|---|---|
| **Real-time data** | Native WebSocket client for live tick streaming via OpenAlgo |
| **Charts** | Lightweight candlestick charts (`lightweight-charts`) with OHLCV history |
| **Order management** | Place, view, and track orders and positions in a single panel |
| **Watchlist** | Persistent, editable watchlists backed by the Python backend (SQLite), with multiple watchlist support |
| **Notifications** | Price alerts for watchlist stocks — 52-week highs/lows, volume breakouts, RSI, MACD, Bollinger Bands, top movers, deals, and insider trades |
| **Market movers** | Top gainers/losers, volume surge stocks, 52-week breakouts |
| **Fundamentals** | Screener.in financials — P/E, ROCE, ROE, quarterly results, and more |
| **Deals** | NSE bulk/block deals and insider trade history via screener.in |
| **News** | MoneyControl company and global news, with AI-powered summaries |
| **Morningstar** | Fair value estimates from Morningstar India, synced nightly |
| **MCP server** | FastAPI backend also exposes all 29 tools as an MCP server (streamable HTTP at `/api/mcp`) for AI assistant integration |
| **Security** | All broker credentials stay server-side; never exposed to the browser |

---

## Architecture

```
Browser
  └── Next.js 16 Frontend (port 3000)
        ├── /api/openalgo/*   → rate-limit → cache → OpenAlgo API (port 8800)
        ├── /api/py/*         → Python FastAPI backend (port 4455)
        ├── /api/settings     → Prisma → SQLite (TopMoverSymbol, UserSettings)
        ├── /api/watchlist    → Python FastAPI backend (multiple watchlists in backend DB)
        └── /api/notifications → Watchlist price alerts

Python FastAPI Backend (port 4455)          ← standalone, no Next.js dependency
  ├── NSE HTTP client (cached, polite delay)
  ├── Screener, MoneyControl, News, AI Summarizer, Morningstar services
  ├── MCP server at /api/mcp (streamable HTTP) — same port 4455
  ├── Alembic migrations (auto-applied on startup)
  └── SQLite data warehouse (data.db)
```

**The Python backend is fully independent.** It can be started, stopped, or replaced without affecting the Next.js process. The frontend degrades gracefully (502 → empty state) if the backend is unreachable.

---

## Quick Start

### Prerequisites

- Node.js 20+
- Python 3.11+
- A running [OpenAlgo](https://github.com/marketcalls/openalgo) instance

### 1 — Clone and install frontend dependencies

```bash
git clone <repo-url> blm_terminal
cd blm_terminal
npm install
npx prisma generate
```

### 2 — Configure environment variables

```bash
cp .env.example .env.local   # create from template (see Configuration below)
```

### 3 — Start the Python analytics backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # edit DB_PATH, PORT, etc.
uvicorn main:app --reload --port 4455
```

### 4 — Start the Next.js frontend

```bash
# from repo root
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

---

## Configuration

### Next.js frontend — `.env.local`

```env
# Server-only (never exposed to the browser)
OPENALGO_URL=http://localhost:8800
OPENALGO_API_KEY=<your_openalgo_api_key>
OPENALGO_TIMEOUT_MS=10000
RATE_LIMIT_PER_MINUTE=60
PYTHON_BACKEND_URL=http://localhost:4455

# Client-safe
NEXT_PUBLIC_OPENALGO_WS_URL=ws://localhost:8765
NEXT_PUBLIC_OPENALGO_DEFAULT_EXCHANGE=NSE
```

> **Never commit `.env.local`.** The `.gitignore` already excludes all `.env*` files.

### Python backend — `backend/.env`

```env
NSE_BASE_URL=https://www.nseindia.com
DB_PATH=./data.db
PORT=4455
NSE_REQUEST_DELAY_MS=500
NSE_CACHE_TTL_SECONDS=3600
LOG_LEVEL=INFO
```


## Development

### Frontend

```bash
npm run dev       # dev server with Turbopack
npm run build     # production build + TypeScript check
npm run lint      # ESLint v9 flat config
npx prisma generate   # regenerate client after schema changes
```

### Python backend

```bash
cd backend
source .venv/bin/activate
uvicorn main:app --reload --port 4455

# Tests (requires running server)
pytest                          # all tests
pytest tests/test_endpoints.py::TestMarketTopGainers::test_structure  # single test
pytest -m "not slow"            # skip NSE-hitting tests
```

---

## Project Structure

```
src/
├── app/
│   ├── api/                  # Next.js API routes (proxy layer)
│   │   ├── openalgo/         # Broker proxy: rate-limit → cache → OpenAlgo
│   │   ├── py/[...path]/     # Catch-all proxy → Python backend
│   │   ├── settings/         # User settings (Prisma/SQLite)
│   │   └── watchlist/        # Watchlist CRUD (proxied to Python backend)
│   ├── globals.css           # Tailwind v4 design tokens
│   ├── layout.tsx
│   └── page.tsx
├── components/
│   ├── widgets/              # ChartWidget, OrderWidget, PosWidget, WatchWidget, …
│   └── …                     # CommandBar, GridSystem, LiveTicker, Panel, ErrorBoundary
├── lib/                      # Shared utilities and singletons
│   ├── socket.ts             # Native WebSocket singleton (wsService)
│   ├── cache.ts              # In-memory TTL cache (Map-backed, fixed-window rate limiter)
│   └── …                     # openalgo.ts, openalgo-server.ts, prisma.ts, logger.ts
└── store/
    └── terminalStore.ts      # All Jotai atoms
backend/                      # FastAPI analytics service (Python ≥ 3.11, Hatch build)
├── app/
│   ├── routers/              # corporatefilings, market, news, screener, watchlist,
│   │                         # stockuniverse, ai_summarizer, notifications, morningstar
│   ├── services/             # nse_client, screener_client, news_fetcher,
│   │                         # moneycontrol_client, ai_summarizer, morningstar_client
│   ├── models/               # SQLAlchemy ORM models (corporatefilings, news,
│   │                         # stockuniverse, watchlist, notifications)
│   ├── schemas/             # Pydantic v2 request/response schemas
│   └── backgroundtasks.py   # Fair value sync, notification worker (scheduled tasks)
├── alembic/                  # DB migrations (auto-applied on startup)
└── main.py                   # FastAPI entrypoint + migration runner
prisma/
└── schema.prisma             # Models: TopMoverSymbol, UserSettings
                              # (watchlist & notifications live in the Python backend DB)
blm-mcp-bundle/              # Claude Desktop MCP plugin
├── server/index.js           # Node.js proxy (stdio → HTTP)
├── manifest.json             # Plugin manifest with 29 tools
├── build.js                  # Cross-platform build script
└── README.md                # Usage instructions
```

---

## Claude Desktop Integration

BLM Terminal includes a **Claude Desktop MCP plugin** that exposes all 29 backend tools directly to Claude. This allows Claude to query NSE market data, screener.in fundamentals, watchlists, news, and Morningstar fair values without needing the Next.js frontend.

### Quick Start

```bash
# Install mcpb CLI
npm install -g @anthropic-ai/mcpb

# Build the bundle (defaults to localhost:4455)
cd blm-mcp-bundle
node build.js

# Or specify a different backend URL
PYTHON_BACKEND_URL=http://192.168.1.100:4455 node build.js
```

This creates `blm-mcp-proxy.mcpb`. Install it in Claude Desktop via **Developer → Extensions → Install Extension**.

See [`blm-mcp-bundle/README.md`](blm-mcp-bundle/README.md) for full documentation.
