# BLM Terminal

![Build](https://img.shields.io/badge/build-passing-brightgreen)
![Next.js](https://img.shields.io/badge/Next.js-16-black?logo=next.js)
![React](https://img.shields.io/badge/React-19-61DAFB?logo=react)
![Python](https://img.shields.io/badge/Python-3.11%2B-blue?logo=python)
![License](https://img.shields.io/badge/license-MIT-blue)

**A self-hosted financial terminal for the OpenAlgo ecosystem** — real-time quotes, candlestick charts, order entry, positions, NSE analytics, and a persistent data warehouse, all in a single browser tab.

---

## Table of Contents

- [Overview](#overview)
- [Key Features](#key-features)
- [Architecture](#architecture)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Docker Deployment](#docker-deployment)
- [Development](#development)
- [Project Structure](#project-structure)

---

## Overview

BLM Terminal is a full-stack trading dashboard that sits in front of an [OpenAlgo](https://github.com/marketcalls/openalgo) broker-agnostic API gateway. The frontend is a Next.js 16 App Router application that proxies all broker calls server-side, keeping API credentials out of the browser. A companion FastAPI service (`backend/`) independently archives NSE India market data and corporate filings into a local SQLite database, acting as a standalone analytics data warehouse.

---

## Key Features

| Area | Detail |
|---|---|
| **Real-time data** | Native WebSocket client for live tick streaming via OpenAlgo |
| **Charts** | Lightweight candlestick charts (`lightweight-charts`) with OHLCV history |
| **Order management** | Place, view, and track orders and positions in a single panel |
| **Watchlist** | Persistent, editable watchlist backed by the Python analytics backend (SQLite) |
| **Market movers** | Top gainers / losers fetched from the Python analytics backend |
| **Fundamentals & Deals** | NSE corporate filings, bulk/block deal data via the FastAPI service |
| **Data warehouse** | Standalone FastAPI + SQLite backend — runs independently; archives OHLCV and filing data with configurable TTL caching |
| **Security** | All broker credentials stay server-side; compatible with SELinux contexts and Cloudflare tunnels |
| **Home-lab friendly** | Docker Compose support with Portainer-ready configuration |

---

## Architecture

```
Browser
  └── Next.js 16 Frontend (port 3000)
        ├── /api/openalgo/*   → rate-limit → cache → OpenAlgo API (port 8800)
        ├── /api/py/*         → Python FastAPI backend (port 4455)
        ├── /api/settings     → Prisma → SQLite (TopMoverSymbol, UserSettings)
        └── /api/watchlist    → Python FastAPI backend (watchlist in backend DB)

Python FastAPI Backend (port 4455)          ← standalone, no Next.js dependency
  ├── NSE HTTP client (cached, polite delay)
  ├── Screener, MoneyControl, News, AI Summarizer services
  ├── MCP server at /api/mcp (streamable HTTP)
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

---

## Docker Deployment

A minimal Docker Compose setup for running both services together, suitable for Portainer or any home-lab environment. Create `docker-compose.yml` in the repo root:

```yaml
version: "3.9"

services:
  frontend:
    build:
      context: .
      dockerfile: Dockerfile          # Next.js standalone build
    ports:
      - "3000:3000"
    env_file: .env.local
    depends_on:
      - backend
    restart: unless-stopped

  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile          # Python FastAPI image
    ports:
      - "8000:8000"
    env_file: ./backend/.env
    volumes:
      - backend_data:/app/data        # persist SQLite warehouse
    restart: unless-stopped

volumes:
  backend_data:
```

### SELinux & Cloudflare Tunnels

- Mount volumes with the `:z` flag (shared) or `:Z` flag (private) to satisfy SELinux relabelling:
  `- backend_data:/app/data:Z`
- Expose the frontend through a Cloudflare tunnel instead of opening ports publicly. Point the tunnel to `http://localhost:3000`; the backend never needs to be directly reachable from the internet.

---

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
│   │                         # stockuniverse, ai_summarizer, nonpersistence
│   ├── services/             # nse_client, screener_client, news_fetcher,
│   │                         # moneycontrol_client, ai_summarizer
│   ├── models/               # SQLAlchemy ORM models (corporatefilings, news,
│   │                         # stockuniverse, watchlist)
│   └── schemas/              # Pydantic v2 request/response schemas
├── alembic/                  # DB migrations (auto-applied on startup)
└── main.py                   # FastAPI entrypoint + migration runner
prisma/
└── schema.prisma             # Models: TopMoverSymbol, UserSettings
                              # (watchlist lives in the Python backend DB)
blm-mcp-bundle/              # Claude Desktop MCP plugin
├── server/index.js           # Node.js proxy (stdio → HTTP)
├── manifest.json             # Plugin manifest with 28 tools
├── build.js                  # Cross-platform build script
└── README.md                # Usage instructions
```

---

## Claude Desktop Integration

BLM Terminal includes a **Claude Desktop MCP plugin** that exposes all 28 backend tools directly to Claude. This allows Claude to query NSE market data, screener.in fundamentals, watchlists, and news without needing the Next.js frontend.

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
