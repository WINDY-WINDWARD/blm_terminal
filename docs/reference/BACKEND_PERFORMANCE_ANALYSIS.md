# Backend Performance Analysis & Optimization Guide

**Document Version:** 1.3  
**Date:** 2026-03-20  
**Author:** AI Engineering Review  
**Status:** Implementation Recommended  
**Changelog:**

- **v1.3 (this version):** Fixed 5 issues from v1.2 peer review:
  1. `get_largeal_snapshot` typo → runtime `AttributeError` crash in `check_block_deals`. Fixed: one-character correction to `get_largedeal_snapshot`.
  2. Circuit breaker timer did not restart when a HALF_OPEN probe failed — `_CIRCUIT_OPENED_AT` was only recorded on first CLOSED→OPEN transition. Fixed: `_record_failure()` now records `_CIRCUIT_OPENED_AT` when either first-open OR HALF_OPEN→OPEN probe failure occurs. Also updated §8.3 state diagram comment to match.
  3. `_get_largedeal_snapshot_shared()` hardcoded `nse_client_async`, breaking Phase 1 when `USE_ASYNC_NSE=false`. Fixed: uses `_active_client` + `is_async_fn=USE_ASYNC_NSE`.
  4. `check_bulk_deals`/`check_block_deals`/`get_high_short_interest` bypassed rate limiter when called from MCP directly (inner `self.get_largedeal_snapshot()` call was unthrottled). Fixed: these three methods now raise `NotImplementedError`; the parsing logic is extracted into `_bulk_deals_from_snapshot()`, `_block_deals_from_snapshot()`, and `_short_interest_from_snapshot()` helpers. The NSE call lives only in `_get_largedeal_snapshot_shared()` (nonpersistence) and `throttled_nse_call` (MCP), making the bypass structurally impossible. §7.2 updated with explicit MCP usage examples for Phase 1 and Phase 2.
  5. `get_top_gainers` and `get_top_losers` each fired a separate HTTP call to the same `live-analysis-market-turnover` URL. Fixed: added `_get_market_turnover()` helper; both gainers and losers call it; upstream caching in `nonpersistence.py` shares one NSE call between both endpoints.

- **v1.2:** Fixed 6 issues from v1.1 peer review: `SQLiteCache.pop()` deadlock (RLock), cross-process TTL (`time.time()` not `monotonic`), circuit breaker half-open implementation, shared snapshot cache pattern, `NSEClientAsync` proper class (not facade), `_NSE_FIELD_MAP` at module level.

- **v1.1:** Fixed 11 issues from v1.0 peer review — stale `last_at` read, `get_event_loop()` deprecation, hand-rolled TTLCache replaced with `cachetools`, thread-safety fix, multi-worker incompatibility flagged, semaphore-gated gather elevated to primary, full async NSE port for all 10 methods, circuit breaker added, SQLite shared cache option, uvloop recommendation added.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Current Architecture Overview](#2-current-architecture-overview)
3. [Performance Measurements](#3-performance-measurements)
4. [Root Cause Analysis](#4-root-cause-analysis)
5. [Bottleneck Inventory (Full Detail)](#5-bottleneck-inventory-full-detail)
6. [Optimization Roadmap](#6-optimization-roadmap)
7. [Phase 1: Quick Wins — Implementation Details](#7-phase-1-quick-wins--implementation-details)
8. [Phase 2: Eliminate Sync Bottleneck](#8-phase-2-eliminate-sync-bottleneck)
9. [Phase 3: Cleanup & Polish](#9-phase-3-cleanup--polish)
10. [Impact Estimates](#10-impact-estimates)
11. [Testing & Verification Plan](#11-testing--verification-plan)
12. [Risk Assessment](#12-risk-assessment)
13. [Recommended Startup Configuration](#13-recommended-startup-configuration)
14. [Appendix A: NSE API Direct URL Reference](#appendix-a-nse-api-direct-url-reference)
15. [Appendix B: httpx Tuning Reference](#appendix-b-httpx-tuning-reference)

---

## 1. Executive Summary

**Problem:** Backend API calls are averaging ~8,000ms per request on LAN. This is unacceptable for a financial terminal where real-time data is critical.

**Root Cause:** A combination of architectural bottlenecks, not a single issue:
1. A **global `asyncio.Lock`** serializing ALL NSE India API calls to one at a time, with a 2-second courtesy delay between requests
2. **Synchronous `nsepython` library** blocking thread-pool threads on every NSE call
3. **NewsFetcher creating a new `httpx.AsyncClient` per request**, resulting in 100+ TCP connections per crawl operation
4. **No httpx connection pool tuning** on any client — defaults are conservative and don't reuse connections
5. **Duplicate rate-limiting locks** in `nonpersistence.py` and `mcp_server.py` that can race against each other
6. **Cache dicts with no eviction** growing unbounded (memory leak)

**Expected Improvement:**
- Phase 1 implementation → **60-70% latency reduction** (from ~8,000ms to ~2,000-3,000ms)
- Phase 2 implementation → **Additional 20-25% reduction** (from ~2,000ms to ~500-1,000ms)
- Phase 3 implementation → Consistent sub-500ms for cached data

**⚠️ Multi-Worker Incompatibility Warning:**

> All in-memory improvements in this document (semaphores, request coalescing dicts, dict-based caches) are **single-process constructs**. Running `uvicorn --workers N` creates N independent Python processes, each with their own copy of every in-memory data structure. This breaks:
> - The NSE semaphore (up to 2×N concurrent NSE calls instead of 2)
> - Request coalescing (N separate dicts, no cross-worker deduplication)
> - In-memory caches (N cold-start caches, no shared state)
>
> **For a single-user single-machine deployment, use `--workers 1`**. If you need more throughput later, the document covers two shared-state options: SQLite in-memory (simple, zero-dependency) and Redis (production-grade, horizontal-scale-ready). See §13 for the full configuration story.

---

## 2. Current Architecture Overview

### 2.1 Technology Stack

| Component | Technology | Notes |
|---|---|---|
| Framework | FastAPI 0.115+ | ASGI application |
| ASGI Server | Uvicorn (standard) | Runs with `reload=False` in production |
| Event Loop | asyncio (default) or uvloop | uvloop is 2-4× faster for I/O workloads; trivial to enable |
| Async HTTP Client | `httpx` 0.28+ | Used by ScreenerClient, NewsFetcher, MarketDataFetcher, NSEClientAsync |
| Sync HTTP Client | `requests` + `nsepython` | NSE India API calls (blocking) — replaced in Phase 2 |
| Database | SQLite + SQLAlchemy (async + sync) | `aiosqlite` for request handlers, `requests` for background threads |
| ORM | SQLAlchemy 2.0+ async | AsyncSession for API routes, sync Session for workers |
| Caching | `cachetools.TTLCache` (single-worker) + `SQLiteCache` (multi-worker future) | See §9.1 |
| MCP Server | `mcp` 1.0+ | Streamable HTTP transport, mounted at `/api/mcp` |
| Browser Cookies | `rookiepy` | Extracts Firefox/Chrome cookies for authenticated scrapers |

### 2.2 Application Entry Point

- **File:** `backend/main.py`
- **Server:** `uvicorn main:app --host 0.0.0.0 --port 8000`
- **Reload:** Disabled in production (`reload=False`)

### 2.3 Directory Structure

```
backend/
├── main.py                          # FastAPI app entry point, lifespan, middleware
├── pyproject.toml                   # Dependencies
├── alembic.ini                      # Alembic configuration
├── data.db                          # SQLite database (WAL mode)
├── app/
│   ├── __init__.py
│   ├── config.py                    # Pydantic-settings singleton
│   ├── database.py                  # Async + Sync SQLAlchemy engines + sessions
│   ├── backgroundtasks.py           # 4 daemon worker threads
│   ├── mcp_server.py                # MCP tool definitions (37 tools) — ⚠️ has duplicate _nse_lock
│   ├── routers/
│   │   ├── nonpersistence.py        # NSE live data endpoints (CRITICAL BOTTLENECK)
│   │   ├── corporatefilings.py      # NSE quarterly filings
│   │   ├── markets.py               # Industry/sector listings (DB-backed)
│   │   ├── news.py                  # Global + company news endpoints
│   │   ├── screener.py              # Screener.in fundamentals
│   │   ├── stockuniverse.py         # Stock universe CRUD
│   │   ├── watchlist.py             # Watchlist CRUD
│   │   └── ai_summarizer.py        # LLM summarization
│   ├── models/                      # SQLAlchemy ORM models
│   ├── schemas/                     # Pydantic request/response schemas
│   └── services/
│       ├── nse_client.py            # NSE API client (sync, BLOCKING — replaced Phase 2)
│       ├── nse_client_async.py      # (NEW in Phase 2) Async NSE client, all 10 methods
│       ├── nse_rate_limiter.py      # (NEW in Phase 1) Shared rate limiter + circuit breaker
│       ├── cache.py                 # (NEW in Phase 3) cachetools + SQLiteCache
│       ├── screener_client.py       # Screener.in authenticated client
│       ├── news_fetcher.py          # MoneyControl scraper (fixed Phase 1)
│       ├── mc_market_fetcher.py     # MoneyControl market data fetcher
│       ├── mc_stock_linker.py       # RapidFuzz symbol matching
│       ├── ai_summarizer.py         # OpenAI-compatible LLM client
│       └── helpers/json_to_csv.py   # NSE JSON → CSV converter
├── alembic/
│   └── versions/                    # 10 migration files
└── tests/
    ├── test_endpoints.py
    ├── test_mcp.py
    └── test_mcp_stdio.py
```

### 2.4 All API Endpoints

| Router | Endpoint | Method | Data Source | Caching | BOTTLENECK? |
|---|---|---|---|---|---|
| `ai_summarizer` | `/api/ai/summarize` | POST | LLM provider | None | No |
| `ai_summarizer` | `/api/ai/health` | GET | LLM ping | None | No |
| `corporatefilings` | `/api/corporatefilings/{symbol}` | GET | NSE + DB | DB: 30-day | Yes (sync NSE) |
| `markets` | `/api/markets/industries` | GET | DB | None | No |
| `markets` | `/api/markets/sectors` | GET | DB | None | No |
| `markets` | `/api/markets/industries/{slug}/stocks` | GET | DB | None | No |
| `markets` | `/api/markets/sectors/{slug}/stocks` | GET | DB | None | No |
| `nonpersistence` | `/api/market/top-gainers` | GET | NSE live | None | **YES — Critical** |
| `nonpersistence` | `/api/market/top-losers` | GET | NSE live | None | **YES — Critical** |
| `nonpersistence` | `/api/market/bulk-deals/{symbol}` | GET | NSE live | 10 min cache | **YES** |
| `nonpersistence` | `/api/market/block-deals/{symbol}` | GET | NSE live | 10 min cache | **YES** |
| `nonpersistence` | `/api/market/high-short-interest` | GET | NSE live | 10 min cache | **YES** |
| `nonpersistence` | `/api/market/largedeal-snapshot` | GET | NSE live | 10 min cache | **YES** |
| `nonpersistence` | `/api/market/change-ranges/{symbol}` | GET | NSE live | 5 min cache | **YES** |
| `nonpersistence` | `/api/market/symbol-data/{symbol}` | GET | NSE live | 1 min cache | **YES** |
| `nonpersistence` | `/api/market/52week-low` | GET | NSE live | 3-hour cache | **YES** |
| `nonpersistence` | `/api/market/52week-high` | GET | NSE live | 3-hour cache | **YES** |
| `nonpersistence` | `/api/market/volume-gainers` | GET | NSE live | 25-min cache | **YES** |
| `news` | `/api/news/global` | GET | DB | None | No |
| `news` | `/api/news/company` | POST | MoneyControl | DB persistence | **YES — Critical** |
| `news` | `/api/news/company/{symbol}` | GET | DB | None | No |
| `screener` | `/api/screener/search` | GET | screener.in | 60 sec cache | Moderate |
| `screener` | `/api/screener/company/{symbol}` | GET | screener.in | 15-min cache | Moderate |
| `screener` | `/api/screener/trades/{symbol}` | GET | screener.in | 15-min cache | Moderate |
| `screener` | `/api/screener/quarterly/{symbol}` | GET | screener.in | 15-min cache | Moderate |
| `stockuniverse` | `/api/stockuniverse` | GET | DB | None | No |
| `stockuniverse` | `/api/stockuniverse/{symbol}` | GET | DB | None | No |
| `stockuniverse` | `/api/stockuniverse/search/{prefix}` | GET | DB | None | No |
| `stockuniverse` | `/api/stockuniverse/run-mc-linker` | POST | DB (fuzzy) | None | No |
| `stockuniverse` | `/api/stockuniverse/pending-review` | GET | DB | None | No |
| `stockuniverse` | `/api/stockuniverse/{symbol}/confirm-match` | PUT | DB | None | No |
| `watchlist` | `/api/watchlists` | GET/POST | DB | None | No |
| `watchlist` | `/api/watchlists/{id}` | DELETE | DB | None | No |
| `watchlist` | `/api/watchlists/{id}/items` | GET/POST | DB | None | No |
| `watchlist` | `/api/watchlists/{id}/items/{item_id}` | DELETE | DB | None | No |
| `watchlist` | `/api/watchlist` (legacy) | GET/POST/DELETE | DB | None | No |
| MCP | `/api/mcp` | POST | NSE/Screener/MC | Per-endpoint | **YES** |
| Meta | `/health` | GET | — | None | No |

---

## 3. Performance Measurements

### 3.1 Observed Symptoms

- **Average API latency:** ~8,000ms per request on LAN
- **First request to any NSE endpoint:** Consistently slow (~5,000-20,000ms)
- **Subsequent requests (within TTL):** Fast (cached)
- **Cache miss scenarios:** When multiple users hit different NSE endpoints simultaneously, all queue behind the global lock
- **Screener endpoints:** ~2,000-5,000ms for first request (due to browser cookie loading + 1s courtesy delay)
- **News crawl endpoints:** ~10,000-30,000ms for full 6-page crawl (120+ HTTP clients created)

### 3.2 Request Flow Analysis (Critical Path)

```
Client Request
    │
    ▼
Next.js Proxy (/api/py/[...path])
    │  (Has its own TTL cache — cache-hit returns fast here)
    │  Cache miss ▼
    ▼
FastAPI Backend (uvicorn)
    │
    ├─► [DB-only endpoints]  ──► SQLite  ──► ~5-50ms ✓
    │
    ├─► [CorporateFilings]    ──► asyncio.to_thread(nsepython) ──► NSE India
    │                           (BLOCKS thread pool, waits for global lock)
    │
    ├─► [NonPersistence]      ──► _nse_lock ──► asyncio.to_thread ──► nsepython ──► NSE India
    │                           (ONE request at a time, 2s delay between)
    │
    ├─► [News Crawl]         ──► _get_client() [NEW CLIENT EACH TIME] ──► MoneyControl
    │                           (120+ TCP connections, rookiepy runs on EVERY call)
    │
    ├─► [Screener]            ──► _screener_lock ──► httpx.AsyncClient ──► screener.in
    │                           (1s delay per request, no connection pool tuning)
    │
    └─► [AI Summarizer]      ──► AsyncOpenAI ──► External LLM API
                                (Network-dependent, no internal bottleneck)
```

### 3.3 Timing Breakdown per Endpoint Type

| Endpoint Type | Components of Latency | Estimated Range |
|---|---|---|
| **DB-only** | SQL query + serialization | 5-50ms |
| **NSE (top-gainers/losers) — cache miss** | Global lock wait + 2s courtesy delay + NSE API (1-5s) + to_thread overhead | 3,000-8,000ms |
| **NSE (symbol-data) — cache miss** | Global lock wait + 2s courtesy delay + NSE API (1-5s) + to_thread overhead | 3,000-8,000ms |
| **NSE (52week-high/low) — cache miss** | Global lock wait + 2s courtesy delay + NSE API (1-5s) + to_thread overhead | 3,000-8,000ms |
| **NSE (with cache hit)** | In-memory dict lookup | <10ms |
| **News crawl (6 pages)** | Cookie load per call (×120) + 120 TCP connections + 1s delay per article | 10,000-30,000ms |
| **News company (per symbol)** | Resolve URL (DB + MC API) + fetch page + parse + article fetch (×N) | 2,000-10,000ms |
| **Screener (first request)** | Browser cookie extraction + 1s delay + HTML fetch + parse | 2,000-5,000ms |
| **Screener (cached)** | In-memory dict lookup | <10ms |
| **AI Summarizer** | LLM API round-trip | Network-dependent |

---

## 4. Root Cause Analysis

### 4.1 Primary Root Cause: Global Serial Lock

**File:** `backend/app/routers/nonpersistence.py`, line 34

```python
_nse_lock = asyncio.Lock()
_last_request_at: float = 0.0  # monotonic timestamp of the last NSE call
```

**Problem:** A single `asyncio.Lock` serializes ALL NSE API calls to ONE at a time. With a 2-second courtesy delay between any two calls, the theoretical maximum throughput is 30 requests/minute.

**Impact:**
- If `top-gainers` takes 5 seconds to respond from NSE, every other NSE endpoint (`symbol-data`, `bulk-deals`, `52week-high`, etc.) is blocked for that duration
- The `_throttled_call()` function acquires this lock for the ENTIRE duration of the NSE call, including `asyncio.sleep()` and `asyncio.to_thread()`

**This is the #1 reason for 8,000ms latency.** Only ONE request processes at a time.

### 4.2 Secondary Root Cause: Synchronous nsepython in Async Context

**File:** `backend/app/services/nse_client.py`

The `nse_client` singleton uses `requests.Session` (synchronous). Every method is synchronous, called via `asyncio.to_thread()` from async routers.

**Problems:**
1. `asyncio.to_thread()` dispatches to Python's default `ThreadPoolExecutor` (usually 40 threads)
2. Each thread is blocked for the duration of the HTTP call (up to 20 seconds)
3. The `nsepython` library makes its own HTTP calls internally with opaque session management
4. No connection pooling control — every `nsepython` call may create new TCP connections

### 4.3 Tertiary Root Cause: Per-Request httpx Client in NewsFetcher

**File:** `backend/app/services/news_fetcher.py`, lines 89-114

```python
async def _get_client(self) -> httpx.AsyncClient:
    client = httpx.AsyncClient(...)  # NEW client every call
    try:
        import rookiepy
        raw = await asyncio.to_thread(rookiepy.firefox, ["moneycontrol.com"])  # EVERY call
        # ... set cookies
    except Exception:
        pass
    return client
```

**Problems:**
1. A NEW `httpx.AsyncClient` is created for EVERY HTTP request
2. `rookiepy.firefox()` (filesystem/OS operation) runs on EVERY `_get_client()` call
3. For a 6-page crawl with 20 articles per page: 126 httpx clients + 126 rookiepy invocations
4. No TCP connection reuse — every request establishes a new connection

---

## 5. Bottleneck Inventory (Full Detail)

### 5.1 Critical Bottlenecks

#### B-1: Global NSE Request Serial Lock
- **Severity:** CRITICAL
- **File:** `backend/app/routers/nonpersistence.py:34`
- **Impact:** Only 1 NSE request executes at a time. Any slow NSE response blocks all others.
- **Fix:** Replace with `asyncio.Semaphore(2)` + per-endpoint keyed locks. See §7.1.
- **Effort:** Medium

#### B-2: Duplicate NSE Lock in MCP Server
- **Severity:** CRITICAL
- **File:** `backend/app/mcp_server.py`
- **Impact:** MCP and REST API use different locks — race condition between them.
- **Fix:** Share the rate limiter via `app/services/nse_rate_limiter.py`. See §7.2.
- **Effort:** Low

#### B-3: Sync nsepython Library Blocking Thread Pool
- **Severity:** CRITICAL
- **File:** `backend/app/services/nse_client.py`
- **Impact:** Each NSE call blocks a thread-pool thread for up to 20 seconds.
- **Fix:** Rewrite to async httpx in `nse_client_async.py`. See §8.1.
- **Effort:** Medium-High

#### B-4: NewsFetcher Creates httpx Client Per Request
- **Severity:** CRITICAL
- **File:** `backend/app/services/news_fetcher.py:89-114`
- **Impact:** 100+ TCP connections per crawl, rookiepy runs 100+ times per crawl
- **Fix:** Persistent client in `init()`. See §7.3.
- **Effort:** Low

### 5.2 High-Severity Bottlenecks

#### B-5: No httpx Connection Pool Tuning
- **Severity:** HIGH
- **Files:** `screener_client.py`, `news_fetcher.py`, `mc_market_fetcher.py`, `nse_client.py`
- **Impact:** Default httpx limits are conservative. No keepalive tuning.
- **Fix:** Add `limits=httpx.Limits(max_connections=20, max_keepalive_connections=10, keepalive_expiry=30.0)` to all clients. See §7.4 and §8.1.
- **Effort:** Low

#### B-6: Screener Lock Serializes All Screener Requests
- **Severity:** HIGH
- **File:** `backend/app/services/screener_client.py:29`
- **Impact:** Only 1 screener.in request at a time, plus 1-second courtesy delay.
- **Fix:** Use `asyncio.Semaphore(2)` instead of `Lock`. See §7.5.
- **Effort:** Low

#### B-7: News Crawl Launches All Tasks Simultaneously
- **Severity:** HIGH
- **File:** `backend/app/services/news_fetcher.py:317-318`
- **Impact:** Semaphore only gates HTTP execution, not coroutine creation. All tasks spawned at once.
- **Fix:** Semaphore-gated gather. See §7.6.
- **Effort:** Low

#### B-8: Cache Dict Memory Leaks
- **Severity:** HIGH
- **Files:** `screener_client.py` (`_HTML_CACHE`, `_trades_id_cache`), `mcp_server.py` (`_CACHE`), `nonpersistence.py` (`_cache`), `screener.py` (`_CACHE`)
- **Impact:** Caches grow unbounded over time.
- **Fix:** Replace with `cachetools.TTLCache` + `SQLiteCache`. See §9.1.
- **Effort:** Low-Medium

#### B-9: No Circuit Breaker for NSE Failures
- **Severity:** MEDIUM-HIGH
- **Impact:** Under NSE outage, the queue fills with waiting tasks.
- **Fix:** Built into `throttled_nse_call`. See §7.1 and §8.3.
- **Effort:** Low

### 5.3 Medium-Severity Bottlenecks

#### B-10: Sequential News Worker Fetches Per Symbol
- **Severity:** MEDIUM
- **Fix:** `asyncio.gather()` with concurrency limit
- **Effort:** Low

#### B-11: Sequential Market Data Worker
- **Severity:** MEDIUM
- **Fix:** `asyncio.gather()` with concurrency limit
- **Effort:** Low

#### B-12: Sequential Stock Universe Sync
- **Severity:** MEDIUM
- **Fix:** Batch fetch symbols, use NSE's bulk equity list endpoint
- **Effort:** Medium

#### B-13: News Date Filtering in Python
- **Severity:** LOW-MEDIUM
- **Fix:** Use SQL `WHERE` clause with date parameter
- **Effort:** Low

### 5.4 Minor Bottlenecks

#### B-14: No HTTP Cache-Control Headers
- All endpoints return no caching directives
- **Fix:** Add `Cache-Control: public, max-age=X` response headers matching TTL

#### B-15: nsepython Session Warmup at Init
- Blocking HTTP call at `nse_client.__init__`
- **Fix:** Lazy warmup on first request, non-blocking

#### B-16: No request deduplication
- **Fix:** Request coalescing built into `throttled_nse_call`. See §7.1.

#### B-17: Duplicate caches between MCP and REST
- **Fix:** Share cache via `cache.py` singleton

---

## 6. Optimization Roadmap

### Phase 1: Quick Wins (Estimated: 60-70% improvement, ~2-3 hours)
| # | Change | File(s) | Impact | Risk |
|---|---|---|---|---|
| 1.1 | Replace `_nse_lock` with `Semaphore(2)` + per-endpoint locks | `nonpersistence.py` | CRITICAL | Low |
| 1.2 | Share lock between MCP and REST via `nse_rate_limiter.py` | `nonpersistence.py`, `mcp_server.py` | CRITICAL | Low |
| 1.3 | Fix NewsFetcher client reuse (persistent client, cookies loaded once) | `news_fetcher.py` | CRITICAL | Low |
| 1.4 | Add httpx limits to all clients | `screener_client.py`, `news_fetcher.py`, `mc_market_fetcher.py` | HIGH | Low |
| 1.5 | Replace `_screener_lock` with `Semaphore(2)` | `screener_client.py` | MEDIUM | Low |
| 1.6 | Fix news crawl concurrency (semaphore-gated gather) | `news_fetcher.py` | HIGH | Low |

### Phase 2: Eliminate Sync Bottleneck (Estimated: Additional 20-25%, ~4-6 hours)
| # | Change | File(s) | Impact | Risk |
|---|---|---|---|---|
| 2.1 | Full async NSEClient — all 10 methods, proper class (not facade) | `nse_client_async.py` | CRITICAL | Medium |
| 2.2 | Add request coalescing with in-flight tracking | `nse_rate_limiter.py` | HIGH | Medium |
| 2.3 | Add circuit breaker with half-open recovery | `nse_rate_limiter.py` | MEDIUM-HIGH | Low |
| 2.4 | Shared snapshot cache for bulk-deals / block-deals / high-short | `nonpersistence.py` | MEDIUM | Low |
| 2.5 | Remove nsepython dependency | `pyproject.toml` | MEDIUM | Low |

### Phase 3: Cleanup & Polish (Estimated: Additional 10%, ~2-3 hours)
| # | Change | File(s) | Impact | Risk |
|---|---|---|---|---|
| 3.1 | Replace all dict caches with `cachetools.TTLCache` | `cache.py` | MEDIUM | Low |
| 3.2 | Add `SQLiteCache` for multi-worker (RLock fix, `time.time()` fix) | `cache.py` | MEDIUM | Low |
| 3.3 | Add Cache-Control response headers | All router endpoints | LOW | Low |
| 3.4 | Parallelize background workers | `backgroundtasks.py` | MEDIUM | Medium |
| 3.5 | Batch stock universe sync | `backgroundtasks.py` | MEDIUM | Medium |

---

## 7. Phase 1: Quick Wins — Implementation Details

### 7.1 Replace Global NSE Lock with Semaphore + Per-Endpoint Locks + Circuit Breaker

**New file:** `backend/app/services/nse_rate_limiter.py`

> **FIXES APPLIED (v1.2):**
> - `last_at` read is correctly placed *inside* `async with endpoint_lock:`
> - `get_running_loop()` used instead of deprecated `get_event_loop()`
> - Circuit breaker half-open state now fully implemented (was documented but never wired up in v1.1)
> - `_circuit_opened_at` tracking added; `_check_circuit()` checks elapsed time to transition OPEN → HALF_OPEN

```python
"""
Shared NSE rate limiter — used by both the REST API (nonpersistence.py)
and the MCP server (mcp_server.py).

Provides:
- A global semaphore limiting concurrent NSE requests (default: 2)
- Per-endpoint courtesy delay to avoid flooding NSE
- Request coalescing: in-flight requests are shared, not duplicated
- A circuit breaker with OPEN → HALF_OPEN → CLOSED recovery
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import defaultdict

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

NSE_CONCURRENCY_LIMIT: int = int(os.getenv("NSE_CONCURRENCY", "2"))
NSE_COURTESY_DELAY_SECONDS: float = float(os.getenv("NSE_COURTESY_DELAY", "1.5"))
CIRCUIT_FAIL_MAX: int = int(os.getenv("NSE_CIRCUIT_FAIL_MAX", "5"))
CIRCUIT_RESET_TIMEOUT: float = float(os.getenv("NSE_CIRCUIT_RESET_TIMEOUT", "60.0"))

# ---------------------------------------------------------------------------
# Global semaphore — limits concurrent NSE requests across ALL endpoints
# ---------------------------------------------------------------------------

_nse_semaphore = asyncio.Semaphore(NSE_CONCURRENCY_LIMIT)

# ---------------------------------------------------------------------------
# Per-endpoint courtesy delay tracking
# ---------------------------------------------------------------------------

_endpoint_locks: dict[str, asyncio.Lock] = {}
_last_request_at: dict[str, float] = defaultdict(float)


def _get_endpoint_lock(key: str) -> asyncio.Lock:
    """Get or create a lock for the given endpoint key."""
    if key not in _endpoint_locks:
        _endpoint_locks[key] = asyncio.Lock()
    return _endpoint_locks[key]


# ---------------------------------------------------------------------------
# Request coalescing — deduplicate in-flight requests
# ---------------------------------------------------------------------------

_inflight: dict[str, asyncio.Future] = {}


# ---------------------------------------------------------------------------
# Circuit breaker state
# ---------------------------------------------------------------------------

_CONSECUTIVE_FAILURES: dict[str, int] = defaultdict(int)
_CIRCUIT_OPEN: dict[str, bool] = defaultdict(bool)
_CIRCUIT_OPENED_AT: dict[str, float] = defaultdict(float)  # v1.2: track when it opened
_CIRCUIT_HALF_OPEN: dict[str, bool] = defaultdict(bool)


class NSEServiceUnavailableError(Exception):
    """Raised when the NSE circuit breaker is open."""
    pass


def _check_circuit(endpoint_name: str) -> None:
    """
    Check if the circuit is open for this endpoint.
    
    State machine:
      CLOSED  → normal operation, proceed
      OPEN    → check if CIRCUIT_RESET_TIMEOUT has elapsed
                - If yes: transition to HALF_OPEN, allow this one probe through
                - If no: raise NSEServiceUnavailableError immediately
      HALF_OPEN → allow through (this is the probe request)
                   - Success → CLOSED (via _record_success)
                   - Failure → OPEN (via _record_failure, timer restarts)
    """
    if not _CIRCUIT_OPEN.get(endpoint_name, False):
        return  # CLOSED — circuit allows traffic

    if _CIRCUIT_HALF_OPEN.get(endpoint_name, False):
        return  # HALF_OPEN — this is the probe request, allow through

    # Circuit is OPEN — check if enough time has passed to transition to HALF_OPEN
    elapsed = time.monotonic() - _CIRCUIT_OPENED_AT.get(endpoint_name, 0)
    if elapsed >= CIRCUIT_RESET_TIMEOUT:
        _CIRCUIT_HALF_OPEN[endpoint_name] = True
        logger.info(
            "Circuit breaker HALF_OPEN for '%s' — allowing probe request after %.0fs",
            endpoint_name,
            elapsed,
        )
        return  # Allow the probe request through

    raise NSEServiceUnavailableError(
        f"Circuit breaker is OPEN for '{endpoint_name}' "
        f"(opened {elapsed:.0f}s ago, reset after {CIRCUIT_RESET_TIMEOUT:.0f}s). "
        f"Will retry automatically."
    )


def _record_success(endpoint_name: str) -> None:
    """Reset all circuit breaker state on a successful call."""
    _CONSECUTIVE_FAILURES[endpoint_name] = 0
    _CIRCUIT_OPEN[endpoint_name] = False
    _CIRCUIT_HALF_OPEN[endpoint_name] = False


def _record_failure(endpoint_name: str) -> None:
    """
    Increment failure count; open circuit if threshold is reached.

    Timer restart rule: _CIRCUIT_OPENED_AT is reset when:
      (a) The circuit first transitions CLOSED → OPEN (first failure batch)
      (b) The circuit transitions HALF_OPEN → OPEN (probe failure)

    Without (b), a probe failure would leave _CIRCUIT_OPENED_AT at the time of
    the original open, and the next _check_circuit() would immediately see
    elapsed >= CIRCUIT_RESET_TIMEOUT again, letting another probe through — turning
    the circuit into a permanent HALF_OPEN state that allows a probe on every request.
    """
    _CONSECUTIVE_FAILURES[endpoint_name] += 1
    if _CONSECUTIVE_FAILURES[endpoint_name] >= CIRCUIT_FAIL_MAX:
        was_half_open = _CIRCUIT_HALF_OPEN.get(endpoint_name, False)
        was_already_open = _CIRCUIT_OPEN.get(endpoint_name, False)
        _CIRCUIT_OPEN[endpoint_name] = True
        _CIRCUIT_HALF_OPEN[endpoint_name] = False
        # Restart timer on: first CLOSED→OPEN, OR HALF_OPEN→OPEN (probe failure)
        if not was_already_open or was_half_open:
            _CIRCUIT_OPENED_AT[endpoint_name] = time.monotonic()
        logger.warning(
            "Circuit breaker OPEN for '%s' after %d consecutive failures "
            "(half_open_probe_failed=%s, timer_restarted=%s)",
            endpoint_name,
            CIRCUIT_FAIL_MAX,
            was_half_open,
            not was_already_open or was_half_open,
        )


# ---------------------------------------------------------------------------
# Core throttled call
# ---------------------------------------------------------------------------

async def throttled_nse_call(
    endpoint_name: str,
    fn,
    *args,
    is_async_fn: bool = False,
):
    """
    Execute an NSE API call with global concurrency limiting, per-endpoint
    courtesy delay, request coalescing, and circuit breaker protection.

    The circuit breaker implements: CLOSED → OPEN → HALF_OPEN → CLOSED.

    Args:
        endpoint_name: Key for per-endpoint lock and courtesy delay tracking.
        fn: Callable to execute. If is_async_fn=True, awaited directly.
            Otherwise run in asyncio.to_thread().
        *args: Positional arguments passed to fn.
        is_async_fn: True when fn is async (Phase 2+), False when using to_thread().

    Returns:
        The result of fn(*args).

    Raises:
        NSEServiceUnavailableError: If the circuit is open for this endpoint.
    """
    # --- Circuit breaker check ---
    _check_circuit(endpoint_name)

    # --- Request coalescing ---
    running_loop = asyncio.get_running_loop()  # v1.2: get_running_loop(), not get_event_loop()

    if endpoint_name in _inflight:
        inflight_future = _inflight[endpoint_name]
        logger.debug(
            "Coalescing request for '%s' — waiting for in-flight result (id=%s)",
            endpoint_name,
            id(inflight_future),
        )
        try:
            return await inflight_future
        except Exception:
            logger.debug("In-flight request for '%s' failed, will retry", endpoint_name)
            del _inflight[endpoint_name]

    inflight_future = running_loop.create_future()
    _inflight[endpoint_name] = inflight_future

    try:
        async with _nse_semaphore:
            # v1.2 FIX: read _last_request_at INSIDE the endpoint lock —
            # prevents stale values when two coroutines race to acquire the lock
            endpoint_lock = _get_endpoint_lock(endpoint_name)
            async with endpoint_lock:
                elapsed = time.monotonic() - _last_request_at[endpoint_name]
                wait = NSE_COURTESY_DELAY_SECONDS - elapsed
                if wait > 0:
                    logger.debug(
                        "NSE courtesy delay: sleeping %.2fs before '%s' request",
                        wait,
                        endpoint_name,
                    )
                    await asyncio.sleep(wait)

                try:
                    if is_async_fn:
                        result = await fn(*args)
                    else:
                        result = await asyncio.to_thread(fn, *args)
                    _record_success(endpoint_name)
                    inflight_future.set_result(result)
                    return result
                except Exception as exc:
                    _record_failure(endpoint_name)
                    inflight_future.set_exception(exc)
                    raise
                finally:
                    _last_request_at[endpoint_name] = time.monotonic()

    finally:
        if endpoint_name in _inflight and _inflight[endpoint_name] is inflight_future:
            del _inflight[endpoint_name]
```

### 7.2 Update MCP Server to Use Shared Limiter

**File:** `backend/app/mcp_server.py`

Remove the local `_nse_lock` definition and import the shared limiter:

```python
# Remove:
# _nse_lock = asyncio.Lock()
# _last_request_at: float = 0.0

# Add:
from app.services.nse_rate_limiter import throttled_nse_call

# v1.3 FIX (B-4): bulk-deals / block-deals / high-short no longer make
# internal NSE calls. The MCP server must fetch the snapshot via throttled_nse_call
# and use the parsing helpers. This is structurally identical to nonpersistence.py.

from app.config import settings

USE_ASYNC_NSE = os.getenv("USE_ASYNC_NSE", "false").lower() == "true"
if USE_ASYNC_NSE:
    from app.services.nse_client_async import nse_client_async as _active_client
else:
    from app.services.nse_client import nse_client as _active_client

# MCP bulk-deals tool:
async def mcp_bulk_deals(symbol: str) -> dict:
    # Fetch the snapshot through the rate limiter (one NSE call)
    snapshot = await throttled_nse_call(
        "bulk-deals:largedeal-snapshot",
        _active_client.get_largedeal_snapshot,
        is_async_fn=USE_ASYNC_NSE,
    )
    # Parse locally — no additional NSE calls
    rows = snapshot.get("BULK_DEALS_DATA", [])
    filtered = [r for r in rows if r.get("symbol", "").upper() == symbol.upper()]
    return {"symbol": symbol, "bulk_deals": filtered}

# MCP block-deals tool:
async def mcp_block_deals(symbol: str) -> dict:
    snapshot = await throttled_nse_call(
        "block-deals:largedeal-snapshot",
        _active_client.get_largedeal_snapshot,
        is_async_fn=USE_ASYNC_NSE,
    )
    rows = snapshot.get("BLOCK_DEALS_DATA", [])
    filtered = [r for r in rows if r.get("symbol", "").upper() == symbol.upper()]
    return {"symbol": symbol, "block_deals": filtered}

# MCP high-short-interest tool:
async def mcp_high_short_interest() -> dict:
    snapshot = await throttled_nse_call(
        "high-short-interest:largedeal-snapshot",
        _active_client.get_largedeal_snapshot,
        is_async_fn=USE_ASYNC_NSE,
    )
    return {"short_deals": snapshot.get("SHORT_DEALS_DATA", [])}
```

### 7.3 Fix NewsFetcher Client Reuse

**Current** (`news_fetcher.py:89-114`): Creates a new `httpx.AsyncClient` per call, runs `rookiepy.firefox()` on every call.

**Fixed:**

```python
class NewsFetcher:
    def __init__(self) -> None:
        self._semaphore: asyncio.Semaphore | None = None
        self._semaphore_loop: asyncio.AbstractEventLoop | None = None
        self._headers = _build_headers(UA_FIREFOX)
        self._cookies_loaded = False
        self._client: httpx.AsyncClient | None = None
        self._client_loop: asyncio.AbstractEventLoop | None = None

    async def init(self) -> None:
        """Initialize persistent httpx client with cookies. Call in lifespan."""
        self._client = httpx.AsyncClient(
            headers=self._headers,
            timeout=httpx.Timeout(30.0, connect=10.0),
            follow_redirects=True,
            limits=httpx.Limits(
                max_connections=10,
                max_keepalive_connections=5,
                keepalive_expiry=30.0,
            ),
        )
        try:
            import rookiepy
            raw = await asyncio.to_thread(rookiepy.firefox, ["moneycontrol.com"])
            if raw:
                for c in raw:
                    domain = str(c.get("domain", ""))
                    name = str(c.get("name", ""))
                    value = str(c.get("value", ""))
                    self._client.cookies.set(name, value, domain=domain or "")
                self._cookies_loaded = True
                logger.debug("Loaded %d cookies into persistent httpx client", len(raw))
        except Exception:
            logger.debug("Could not load cookies — proceeding without authentication")
            self._cookies_loaded = False

    async def _get_client(self) -> httpx.AsyncClient:
        """Return the persistent client, initializing lazily if needed."""
        if self._client is None:
            await self.init()
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
```

**Update `main.py` lifespan:**
```python
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # ...
    await screener_client.init()
    await news_fetcher.init()  # ← NEW

    # On shutdown:
    await news_fetcher.close()  # ← NEW
```

### 7.4 Add httpx Connection Limits to All Clients

**screener_client.py** — update `init()`:
```python
self._http = httpx.AsyncClient(
    base_url=BASE_URL,
    cookies=self._cookies,
    headers={...},
    timeout=15.0,
    follow_redirects=True,
    limits=httpx.Limits(
        max_connections=10,
        max_keepalive_connections=5,
        keepalive_expiry=30.0,
    ),
)
```

**mc_market_fetcher.py** — apply the same pattern.

### 7.5 Replace Screener Lock with Semaphore

```python
# screener_client.py — replace:
# _screener_lock = asyncio.Lock()
# With:
_screener_semaphore = asyncio.Semaphore(2)

# Update usages:
# Before:
async with _screener_lock:
    resp = await self._http.get(url)
    await asyncio.sleep(_COURTESY_DELAY)

# After:
async with _screener_semaphore:
    resp = await self._http.get(url)
    await asyncio.sleep(_COURTESY_DELAY)
```

### 7.6 Fix News Crawl Concurrency — Semaphore-Gated Gather (Primary Pattern)

> **v1.2 note:** Batch processing is secondary. Semaphore-gated gather is primary — it always keeps exactly N tasks running, unlike batches which idle when the slowest task in a batch is slow.

```python
async def crawl_and_store(self, pages: int, db: AsyncSession) -> int:
    # ... URL extraction (unchanged) ...

    if not new_urls:
        return 0

    sem = asyncio.Semaphore(CONCURRENCY_LIMIT)  # CONCURRENCY_LIMIT = 3

    async def bounded_fetch(url: str) -> dict[str, Any] | None:
        async with sem:
            return await self._fetch_and_parse_article(url)

    # All coroutines are created immediately; the semaphore gates execution.
    # At most 3 HTTP requests run concurrently at any time.
    all_results = await asyncio.gather(
        *[bounded_fetch(url) for url in new_urls],
        return_exceptions=True,
    )

    valid_results = [r for r in all_results if isinstance(r, dict)]
    logger.debug("Valid results: %d/%d", len(valid_results), len(new_urls))

    # ... rest of storage logic unchanged ...
```

**Python 3.11+ alternative** using `TaskGroup`:
```python
async with asyncio.TaskGroup() as tg:
    tasks = [tg.create_task(bounded_fetch(url)) for url in new_urls]
# Handle results manually since TaskGroup.__aexit__ propagates exceptions:
results = [t.result() if not t.exception() else None for t in tasks]
```

**Batch approach (secondary — only for memory-sensitive large crawls):**
```python
BATCH_SIZE = 10
for i in range(0, len(new_urls), BATCH_SIZE):
    batch = new_urls[i : i + BATCH_SIZE]
    sem = asyncio.Semaphore(CONCURRENCY_LIMIT)
    async def bounded_fetch(url: str) -> dict | None:
        async with sem:
            return await self._fetch_and_parse_article(url)
    batch_results = await asyncio.gather(*[bounded_fetch(u) for u in batch])
    for r in batch_results:
        if isinstance(r, dict):
            valid_results.append(r)
```

---

## 8. Phase 2: Eliminate Sync Bottleneck

### 8.1 Full Async NSEClient — All 10 Methods (v1.2)

> **FIXES APPLIED (v1.2):**
> - `NSEClientAsync` is now a proper class with instance state (`self._http`), not a facade over module-level functions with ignored `self`
> - `check_bulk_deals`/`check_block_deals`/`get_high_short_interest` no longer call `get_largedeal_snapshot()` directly — they return the data and the caller uses a shared cache (see §8.1 shared snapshot pattern)
> - `_NSE_FIELD_MAP` moved to module level (was inside `get_change_ranges()`)
> - All httpx calls use `limits=httpx.Limits(...)` for connection pooling

**New file:** `backend/app/services/nse_client_async.py`

```python
"""
Async NSE India client — replaces nsepython with direct httpx calls.

All methods are async. No requests.Session, no nsepython, no to_thread().
Uses a shared httpx.AsyncClient with connection pooling.

Design: proper class with instance state. Self._http is created lazily
on first use and reused for all subsequent requests within the process.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

NSE_BASE_URL = "https://www.nseindia.com"
NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}

# v1.2 FIX: _NSE_FIELD_MAP is a constant — move to module level
NSE_FIELD_MAP_CHANGE_RANGES: dict[str, str] = {
    "oneDayPercent": "yesterday_chng_per",
    "oneWeekPercent": "one_week_chng_per",
    "oneMonthPercent": "one_month_chng_per",
    "threeMonthPercent": "three_month_chng_per",
    "sixMonthPercent": "six_month_chng_per",
    "oneYearPercent": "one_year_chng_per",
    "twoYearPercent": "two_year_chng_per",
    "threeYearPercent": "three_year_chng_per",
    "fiveYearPercent": "five_year_chng_per",
}


class NSEClientAsync:
    """
    Async NSE client with proper instance state.

    Use as a singleton:
        nse_client = NSEClientAsync()
        data = await nse_client.get_52week_high_stocks()
    """

    def __init__(self) -> None:
        self._http: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Lazily create the persistent httpx client with NSE cookie warmup."""
        if self._http is None:
            self._http = httpx.AsyncClient(
                base_url=NSE_BASE_URL,
                headers=NSE_HEADERS,
                timeout=httpx.Timeout(20.0, connect=10.0),
                follow_redirects=True,
                limits=httpx.Limits(
                    max_connections=10,
                    max_keepalive_connections=5,
                    keepalive_expiry=30.0,
                ),
            )
            logger.info("NSEClientAsync: creating httpx client — warming cookie session")
            try:
                await self._http.get("/")
                logger.info("NSEClientAsync: cookie session warmed successfully")
            except Exception as exc:
                logger.warning("NSEClientAsync: cookie warmup failed: %s", exc)

        return self._http

    async def close(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _clean_df(self, df: pd.DataFrame) -> pd.DataFrame:
        return df.replace({np.nan: None, pd.NA: None})

    # ------------------------------------------------------------------
    # 52-week and volume endpoints — return plain dict
    # ------------------------------------------------------------------

    async def get_52week_low_stocks(self) -> dict[str, Any]:
        url = "https://www.nseindia.com/api/live-analysis-data-52weeklowstock"
        client = await self._get_client()
        t0 = time.perf_counter()
        resp = await client.get(url)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.info("NSE GET %s → %d (%.0fms)", url, resp.status_code, elapsed_ms)
        resp.raise_for_status()
        payload: dict[str, Any] = resp.json()
        if not isinstance(payload, dict) or "data" not in payload:
            raise ValueError(f"Unexpected 52week-low response: {payload!r}")
        return payload

    async def get_52week_high_stocks(self) -> dict[str, Any]:
        url = "https://www.nseindia.com/api/live-analysis-data-52weekhighstock"
        client = await self._get_client()
        t0 = time.perf_counter()
        resp = await client.get(url)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.info("NSE GET %s → %d (%.0fms)", url, resp.status_code, elapsed_ms)
        resp.raise_for_status()
        payload: dict[str, Any] = resp.json()
        if not isinstance(payload, dict) or "data" not in payload:
            raise ValueError(f"Unexpected 52week-high response: {payload!r}")
        return payload

    async def get_volume_gainers(self) -> dict[str, Any]:
        url = "https://www.nseindia.com/api/live-analysis-volume-gainers"
        client = await self._get_client()
        t0 = time.perf_counter()
        resp = await client.get(url)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.info("NSE GET %s → %d (%.0fms)", url, resp.status_code, elapsed_ms)
        resp.raise_for_status()
        payload: dict[str, Any] = resp.json()
        if not isinstance(payload, dict) or "data" not in payload:
            raise ValueError(f"Unexpected volume-gainers response: {payload!r}")
        return payload

    # ------------------------------------------------------------------
    # Largedeal snapshot — ONE call returns all three deal types
    # This replaces three separate upstream calls.
    # ------------------------------------------------------------------

    async def get_largedeal_snapshot(self) -> dict[str, Any]:
        """
        Fetch bulk/block/short deals in a single NSE API call.

        Returns:
            dict with: as_on_date, BULK_DEALS_DATA, BLOCK_DEALS_DATA, SHORT_DEALS_DATA
        """
        url = "https://www.nseindia.com/api/snapshot-capital-market-largedeal"
        client = await self._get_client()
        t0 = time.perf_counter()
        resp = await client.get(url)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.info("NSE GET %s → %d (%.0fms)", url, resp.status_code, elapsed_ms)
        resp.raise_for_status()
        payload: dict[str, Any] = resp.json()

        expected_keys = {"as_on_date", "BULK_DEALS_DATA", "SHORT_DEALS_DATA", "BLOCK_DEALS_DATA"}
        missing = [k for k in expected_keys if k not in payload]
        if missing:
            logger.warning("Largedeal snapshot missing keys: %s", ", ".join(missing))
        return payload

    # ------------------------------------------------------------------
    # Change ranges and symbol data — return plain dict
    # ------------------------------------------------------------------

    async def get_change_ranges(self, symbol: str) -> dict[str, float]:
        url = (
            "https://www.nseindia.com/api/NextApi/apiClient/GetQuoteApi"
            f"?functionName=getYearwiseData&symbol={symbol}EQN"
        )
        client = await self._get_client()
        t0 = time.perf_counter()
        resp = await client.get(url)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.info("NSE GET %s → %d (%.0fms)", url, resp.status_code, elapsed_ms)
        resp.raise_for_status()
        payload: list[dict[str, Any]] = resp.json()
        if not isinstance(payload, list) or len(payload) == 0:
            raise ValueError(f"Unexpected getYearwiseData response for {symbol}: {payload!r}")

        row = payload[0]
        result: dict[str, float] = {}
        for out_key, nse_key in NSE_FIELD_MAP_CHANGE_RANGES.items():
            raw = row.get(nse_key)
            if raw is None:
                result[out_key] = float("nan")
            else:
                try:
                    result[out_key] = float(raw)
                except (TypeError, ValueError):
                    result[out_key] = float("nan")
        return result

    async def get_symbol_data(self, symbol: str) -> dict[str, Any]:
        url = (
            "https://www.nseindia.com/api/NextApi/apiClient/GetQuoteApi"
            f"?functionName=getSymbolData&marketType=N&series=EQ&symbol={symbol}"
        )
        client = await self._get_client()
        t0 = time.perf_counter()
        resp = await client.get(url)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.info("NSE GET %s → %d (%.0fms)", url, resp.status_code, elapsed_ms)
        resp.raise_for_status()
        payload: dict[str, Any] = resp.json()
        if not isinstance(payload, dict):
            raise ValueError(f"Unexpected getSymbolData response for {symbol}: {payload!r}")
        return payload

    # ------------------------------------------------------------------
    # Market turnover — shared HTTP fetch for top_gainers and top_losers
    # The NSE API returns the same payload; sort direction differs.
    # v1.3 FIX: Both get_top_gainers and get_top_losers must call
    # _get_market_turnover() so nonpersistence.py can cache the payload once.
    # ------------------------------------------------------------------

    async def _get_market_turnover(self) -> list[dict[str, Any]]:
        """
        Fetch the raw market turnover payload from NSE.

        Used by both get_top_gainers and get_top_losers to avoid firing
        two separate HTTP calls to the same endpoint. Callers must cache
        the result upstream (e.g. in nse_cache) so both endpoints share
        one NSE call when invoked simultaneously.
        """
        url = "https://www.nseindia.com/api/live-analysis-market-turnover"
        client = await self._get_client()
        t0 = time.perf_counter()
        resp = await client.get(url)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.info("NSE GET %s → %d (%.0fms)", url, resp.status_code, elapsed_ms)
        resp.raise_for_status()
        payload: dict[str, Any] = resp.json()
        rows: list[dict[str, Any]] = payload.get("data", [])
        if not rows:
            raise ValueError("No data in market turnover response")
        return rows

    # ------------------------------------------------------------------
    # Top gainers / top losers — return DataFrame
    # Uses _get_market_turnover() so callers can cache one shared payload.
    # Falls back to nsepython via to_thread if the JSON endpoint fails.
    # ------------------------------------------------------------------

    async def get_top_gainers(self) -> pd.DataFrame:
        """Fetch today's top-gaining equities on NSE India."""
        try:
            rows = await self._get_market_turnover()
            df = pd.DataFrame(rows)
            if "symbol" not in df.columns or "pChange" not in df.columns:
                raise ValueError(f"Unexpected columns: {df.columns.tolist()}")

            df_eq = df[df["series"] == "EQ"].copy()
            df_eq["pChange"] = pd.to_numeric(df_eq["pChange"], errors="coerce")
            df_eq = df_eq.dropna(subset=["pChange"])
            df_eq = df_eq.sort_values("pChange", ascending=False).head(20)

            logger.info("NSE top gainers: %d rows from market turnover", len(df_eq))
            return self._clean_df(df_eq)

        except Exception as exc:
            logger.warning("Market turnover JSON failed (%s), falling back to nsepython", exc)
            import nsepython
            return await asyncio.to_thread(nsepython.nse_get_top_gainers)

    async def get_top_losers(self) -> pd.DataFrame:
        """Fetch today's top-losing equities on NSE India."""
        try:
            rows = await self._get_market_turnover()
            df = pd.DataFrame(rows)
            if "symbol" not in df.columns or "pChange" not in df.columns:
                raise ValueError(f"Unexpected columns: {df.columns.tolist()}")

            df_eq = df[df["series"] == "EQ"].copy()
            df_eq["pChange"] = pd.to_numeric(df_eq["pChange"], errors="coerce")
            df_eq = df_eq.dropna(subset=["pChange"])
            df_eq = df_eq.sort_values("pChange", ascending=True).head(20)

            logger.info("NSE top losers: %d rows from market turnover", len(df_eq))
            return self._clean_df(df_eq)

        except Exception as exc:
            logger.warning("Market turnover JSON failed (%s), falling back to nsepython", exc)
            import nsepython
            return await asyncio.to_thread(nsepython.nse_get_top_losers)

    async def check_bulk_deals(self, symbol: str) -> pd.DataFrame:
        """
        Fetch today's bulk deals for a specific symbol.
        
        Note: This method takes a pre-fetched snapshot as a parameter.
        The NSE API call must only ever live inside throttled_nse_call() —
        either in nonpersistence.py (_get_largedeal_snapshot_shared) or in
        MCP route handlers. Calling this method with a None snapshot is
        an error. This design makes rate-limiter bypass structurally impossible.
        """
        raise NotImplementedError(
            "check_bulk_deals must be called with a pre-fetched snapshot. "
            "Use _bulk_deals_from_snapshot() for the parsing logic, "
            "and _get_largedeal_snapshot_shared() (nonpersistence) or "
            "throttled_nse_call() (MCP) for the NSE fetch."
        )

    async def check_block_deals(self, symbol: str) -> pd.DataFrame:
        raise NotImplementedError(
            "check_block_deals must be called with a pre-fetched snapshot. "
            "Use _block_deals_from_snapshot() for the parsing logic."
        )

    async def get_high_short_interest(self) -> pd.DataFrame:
        raise NotImplementedError(
            "get_high_short_interest must be called with a pre-fetched snapshot. "
            "Use _short_interest_from_snapshot() for the parsing logic."
        )

    # ------------------------------------------------------------------
    # Snapshot parsing helpers — no NSE calls, safe to call from anywhere.
    # The NSE call lives only in _get_largedeal_snapshot_shared() and
    # throttled_nse_call(); these helpers are called with the result.
    # ------------------------------------------------------------------

    def _bulk_deals_from_snapshot(self, symbol: str, snapshot: dict) -> pd.DataFrame:
        rows = snapshot.get("BULK_DEALS_DATA", [])
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        if "symbol" in df.columns:
            df = df[df["symbol"].str.upper() == symbol.upper()]
        logger.debug("Bulk deals for %s — %d matching rows", symbol, len(df))
        return self._clean_df(df)

    def _block_deals_from_snapshot(self, symbol: str, snapshot: dict) -> pd.DataFrame:
        rows = snapshot.get("BLOCK_DEALS_DATA", [])
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        if "symbol" in df.columns:
            df = df[df["symbol"].str.upper() == symbol.upper()].copy()
        logger.debug("Block deals for %s — %d matching rows", symbol, len(df))
        return self._clean_df(df)

    def _short_interest_from_snapshot(self, snapshot: dict) -> pd.DataFrame:
        rows = snapshot.get("SHORT_DEALS_DATA", [])
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        logger.info("High short interest: %d rows", len(df))
        return self._clean_df(df)

    # ------------------------------------------------------------------
    # Infrequently-used methods — kept as sync stubs with to_thread()
    # ------------------------------------------------------------------

    def get_stock_list(self) -> list[str]:
        import nsepython
        return nsepython.nse_eq_symbols()

    def get_stock_metadata(self, symbol: str) -> dict[str, Any]:
        import nsepython
        return nsepython.nse_eq(symbol)

    def get_corporate_filing_comparison(self, symbol: str) -> str:
        from app.services.helpers.json_to_csv import dict_to_csv_text
        import nsepython
        data = nsepython.nse_past_results(symbol)
        return dict_to_csv_text(data)


nse_client_async = NSEClientAsync()
```

### 8.1 Shared Snapshot Cache Pattern (v1.2 Fix — Bypass of Rate Limiter)

> **v1.2 FIX (B-4):** In v1.1, `check_bulk_deals`, `check_block_deals`, and `get_high_short_interest` each called `get_largedeal_snapshot()` directly (not via `throttled_nse_call`). This fires 3 NSE calls to the same URL simultaneously when all three endpoints are hit at once. The fix: cache the snapshot at the endpoint level so all three derive from one upstream fetch.

**In `nonpersistence.py` — shared snapshot cache:**

```python
from app.services.cache import nse_cache  # cachetools.TTLCache instance
from app.config import settings

USE_ASYNC_NSE = os.getenv("USE_ASYNC_NSE", "false").lower() == "true"
if USE_ASYNC_NSE:
    from app.services.nse_client_async import nse_client_async as _active_client
else:
    from app.services.nse_client import nse_client as _active_client

# Shared snapshot: all three deal types (bulk/block/short) from one NSE call.
# Uses _active_client so it works in both Phase 1 (sync nsepython) and Phase 2 (async).
async def _get_largedeal_snapshot_shared() -> dict:
    """
    Fetch largedeal snapshot once; derive bulk/block/short from it.
    Cached for 10 minutes so concurrent requests for bulk-deals:X,
    block-deals:X, and high-short-interest all share the same upstream fetch.
    
    Works in Phase 1 (sync nsepython via to_thread) and Phase 2 (async httpx).
    """
    cached = nse_cache.get("largedeal-snapshot")
    if cached is not None:
        logger.debug("Shared snapshot cache hit")
        return cached

    # v1.3 FIX: Use _active_client so Phase 1 (USE_ASYNC_NSE=false) still works.
    # In Phase 1: is_async_fn=False → to_thread wraps the sync nsepython call.
    # In Phase 2: is_async_fn=True → awaited directly as async method.
    data = await throttled_nse_call(
        "largedeal-snapshot",
        _active_client.get_largedeal_snapshot,
        is_async_fn=USE_ASYNC_NSE,
    )
    nse_cache["largedeal-snapshot"] = data
    return data


async def bulk_deals(symbol: str) -> JSONResponse:
    cache_key = f"bulk-deals:{symbol.upper()}"
    cached = nse_cache.get(cache_key)
    if cached is not None:
        return JSONResponse(content=cached)

    snapshot = await _get_largedeal_snapshot_shared()
    rows = [
        r for r in snapshot.get("BULK_DEALS_DATA", [])
        if r.get("symbol", "").upper() == symbol.upper()
    ]
    nse_cache[cache_key] = rows
    return JSONResponse(content=rows)


async def block_deals(symbol: str) -> JSONResponse:
    cache_key = f"block-deals:{symbol.upper()}"
    cached = nse_cache.get(cache_key)
    if cached is not None:
        return JSONResponse(content=cached)

    snapshot = await _get_largedeal_snapshot_shared()
    rows = [
        r for r in snapshot.get("BLOCK_DEALS_DATA", [])
        if r.get("symbol", "").upper() == symbol.upper()
    ]
    nse_cache[cache_key] = rows
    return JSONResponse(content=rows)


async def high_short_interest() -> JSONResponse:
    cached = nse_cache.get("high-short-interest")
    if cached is not None:
        return JSONResponse(content=cached)

    snapshot = await _get_largedeal_snapshot_shared()
    data = snapshot.get("SHORT_DEALS_DATA", [])
    nse_cache["high-short-interest"] = data
    return JSONResponse(content=data)


# v1.3 FIX (B-5): Market turnover shared cache.
# Both top-gainers and top-losers hit the same NSE URL.
# Cache the payload once so simultaneous requests share one upstream call.
async def _get_market_turnover_shared() -> list[dict]:
    """Fetch market turnover payload once; cache for subsequent calls."""
    cached = nse_cache.get("market-turnover")
    if cached is not None:
        logger.debug("Market turnover cache hit")
        return cached

    rows = await throttled_nse_call(
        "market-turnover",
        _active_client._get_market_turnover,
        is_async_fn=USE_ASYNC_NSE,
    )
    nse_cache["market-turnover"] = rows
    return rows


async def top_gainers() -> JSONResponse:
    cached = nse_cache.get("top-gainers")
    if cached is not None:
        return JSONResponse(content=cached)

    rows = await _get_market_turnover_shared()
    df = pd.DataFrame(rows)
    df_eq = df[df["series"] == "EQ"].copy()
    df_eq["pChange"] = pd.to_numeric(df_eq["pChange"], errors="coerce")
    df_eq = df_eq.dropna(subset=["pChange"])
    df_eq = df_eq.sort_values("pChange", ascending=False).head(20)
    data = _df_to_json_dict(df_eq)
    nse_cache["top-gainers"] = data
    return JSONResponse(content=data)


async def top_losers() -> JSONResponse:
    cached = nse_cache.get("top-losers")
    if cached is not None:
        return JSONResponse(content=cached)

    rows = await _get_market_turnover_shared()
    df = pd.DataFrame(rows)
    df_eq = df[df["series"] == "EQ"].copy()
    df_eq["pChange"] = pd.to_numeric(df_eq["pChange"], errors="coerce")
    df_eq = df_eq.dropna(subset=["pChange"])
    df_eq = df_eq.sort_values("pChange", ascending=True).head(20)
    data = _df_to_json_dict(df_eq)
    nse_cache["top-losers"] = data
    return JSONResponse(content=data)
```

### 8.2 Request Coalescing

Already built into `throttled_nse_call` (§7.1). If 5 requests arrive simultaneously for `top-gainers` (cache empty): only 1 NSE call fires, 4 wait for the same result.

### 8.3 Circuit Breaker State Machine

```
CLOSED (normal)
  │  5 consecutive failures
  ▼
OPEN  (reject all requests immediately)
  │  wait CIRCUIT_RESET_TIMEOUT (60s)
  │  transition:
  ▼
HALF_OPEN  (allow 1 probe request through)
  │
  ├─ success → CLOSED (reset failure count)
  └─ failure → OPEN (timer restarts)
```

The implementation is fully wired in `nse_rate_limiter.py`:
- `_check_circuit()`: checks elapsed time since OPEN, transitions to HALF_OPEN when timeout expires
- `_record_failure()`: records `_CIRCUIT_OPENED_AT` on first open (CLOSED→OPEN) AND on probe failure (HALF_OPEN→OPEN), so the timeout always restarts correctly
- `_record_success()`: resets all state on success

---

## 9. Phase 3: Cleanup & Polish

### 9.1 Replace All Dict Caches with cachetools / SQLite Shared Cache

> **FIXES APPLIED (v1.2):**
> - `pop()` deadlock: switched from `threading.Lock()` to `threading.RLock()` (reentrant) and inlined the read so `get()` is never called under the lock
> - Cross-process TTL: replaced `time.monotonic()` with `time.time()` throughout `SQLiteCache` — `monotonic()` is process-local and cannot synchronize expiry across workers; `time.time()` is wall-clock and consistent across all processes

**Add dependency:**
```bash
pip install cachetools
```

**New file:** `backend/app/services/cache.py`

```python
"""
Shared caching layer for the BLM backend.

Provides two backends:

1. In-process cache: cachetools.TTLCache
   - Thread-safe (RLock internally)
   - Per-process — NOT shared across workers
   - Best for: single-worker deployments

2. SQLite shared cache: SQLiteCache (v1.2 fixes applied)
   - Shared across all workers on the same machine
   - Uses WAL mode for concurrent reads during writes
   - RLock used instead of Lock to prevent deadlock in pop()
   - time.time() used instead of time.monotonic() for cross-process TTL
   - Zero additional dependencies
   - Best for: multi-worker deployments
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from typing import Any

from cachetools import TTLCache as _TTLCache

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 1. In-process cache — cachetools (single-worker)
# ---------------------------------------------------------------------------

nse_cache = _TTLCache(maxsize=200, ttl=600.0)            # 10-min default
screener_html_cache = _TTLCache(maxsize=500, ttl=900.0)   # 15-min default
screener_search_cache = _TTLCache(maxsize=200, ttl=60.0)  # 1-min default
mcp_cache = _TTLCache(maxsize=200, ttl=600.0)            # 10-min default

# cachetools.TTLCache is thread-safe (RLock). Auto-evicts expired entries.
# Usage:
#   from app.services.cache import nse_cache
#   if nse_cache.get("top-gainers") is None:
#       nse_cache["top-gainers"] = data


# ---------------------------------------------------------------------------
# 2. SQLite shared cache — v1.2 fixes applied
# ---------------------------------------------------------------------------

class SQLiteCache:
    """
    A SQLite-backed key-value cache shared across uvicorn workers.
    
    Uses WAL mode so reads don't block writes.
    TTL uses wall-clock time (time.time()) so it is consistent across processes.
    RLock is used instead of Lock to prevent deadlock in pop().
    """

    _DDL = """
    CREATE TABLE IF NOT EXISTS shared_cache (
        key       TEXT PRIMARY KEY,
        value     TEXT NOT NULL,
        expires_at REAL NOT NULL,
        created_at REAL NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_expires ON shared_cache(expires_at);
    """

    def __init__(
        self,
        db_path: str | None = None,
        max_size: int = 1000,
        default_ttl: float = 600.0,
    ) -> None:
        self._db_path = db_path or "/tmp/blm_shared_cache.db"
        self._max_size = max_size
        self._default_ttl = default_ttl

        # v1.2 FIX 1: RLock instead of Lock.
        # RLock allows the same thread to acquire it multiple times.
        # This is required because pop() holds the lock while calling
        # _get_conn(), and _get_conn() also uses the lock for thread-safety.
        self._lock = threading.RLock()

        # Thread-local SQLite connections
        self._local = threading.local()

        # Initialize DB
        with self._get_conn() as conn:
            conn.executescript(self._DDL)
            conn.commit()

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(
                self._db_path,
                timeout=10.0,
                check_same_thread=False,
            )
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            self._local.conn = conn
        return self._local.conn

    def get(self, key: str) -> Any | None:
        """Get a value. Returns None if missing, expired, or on error."""
        with self._lock:
            try:
                conn = self._get_conn()
                # v1.2 FIX 2: time.time() instead of time.monotonic().
                # monotonic() is process-local and starts from an arbitrary point.
                # time.time() is wall-clock and consistent across all workers.
                now = time.time()
                row = conn.execute(
                    "SELECT value, expires_at FROM shared_cache WHERE key = ?",
                    (key,),
                ).fetchone()

                if row is None:
                    return None

                value_json, expires_at = row
                if now >= expires_at:
                    conn.execute("DELETE FROM shared_cache WHERE key = ?", (key,))
                    conn.commit()
                    return None

                return json.loads(value_json)

            except Exception:
                logger.debug("SQLiteCache.get('%s') failed", key)
                return None

    def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        """Set a value with TTL. Overwrites existing."""
        with self._lock:
            try:
                conn = self._get_conn()
                # v1.2 FIX 2: time.time() for cross-process consistency
                now = time.time()
                effective_ttl = ttl if ttl is not None else self._default_ttl
                expires_at = now + effective_ttl
                value_json = json.dumps(value)

                conn.execute(
                    "INSERT OR REPLACE INTO shared_cache (key, value, expires_at, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (key, value_json, expires_at, now),
                )
                conn.commit()

                # LRU-ish eviction when over max_size
                count_row = conn.execute("SELECT COUNT(*) FROM shared_cache").fetchone()
                if count_row and count_row[0] > self._max_size:
                    conn.execute(
                        "DELETE FROM shared_cache WHERE expires_at < ?",
                        (now,),
                    )
                    remaining = conn.execute("SELECT COUNT(*) FROM shared_cache").fetchone()[0]
                    if remaining > self._max_size:
                        to_delete = remaining - self._max_size
                        conn.execute(
                            f"DELETE FROM shared_cache WHERE key IN "
                            f"(SELECT key FROM shared_cache ORDER BY created_at ASC LIMIT {to_delete})"
                        )
                    conn.commit()

            except Exception:
                logger.debug("SQLiteCache.set('%s') failed", key)

    def pop(self, key: str, default: Any = None) -> Any | None:
        """
        Delete a key and return the value (or default if missing).
        
        v1.2 FIX 1: This method MUST NOT call self.get() because pop() already
        holds self._lock and self.get() also tries to acquire self._lock.
        threading.Lock() is NOT reentrant — this would deadlock.
        We use threading.RLock() AND inline the read logic to be safe.
        """
        with self._lock:
            try:
                conn = self._get_conn()
                now = time.time()  # v1.2 FIX 2: time.time()
                row = conn.execute(
                    "SELECT value, expires_at FROM shared_cache WHERE key = ?",
                    (key,),
                ).fetchone()
                conn.execute("DELETE FROM shared_cache WHERE key = ?", (key,))
                conn.commit()

                if row is None:
                    return default

                value_json, expires_at = row
                if now >= expires_at:
                    return default

                return json.loads(value_json)

            except Exception:
                logger.debug("SQLiteCache.pop('%s') failed", key)
                return default

    def __len__(self) -> int:
        with self._lock:
            conn = self._get_conn()
            now = time.time()  # v1.2 FIX 2: time.time()
            row = conn.execute(
                "SELECT COUNT(*) FROM shared_cache WHERE expires_at >= ?",
                (now,),
            ).fetchone()
            return row[0] if row else 0

    def clear(self) -> None:
        with self._lock:
            conn = self._get_conn()
            conn.execute("DELETE FROM shared_cache")
            conn.commit()


# Global shared cache instance — initialized lazily
_shared_cache: SQLiteCache | None = None
_shared_cache_lock = threading.Lock()


def get_shared_cache() -> SQLiteCache:
    """Get the singleton shared SQLite cache."""
    global _shared_cache
    if _shared_cache is None:
        with _shared_cache_lock:
            if _shared_cache is None:
                cache_db_path = os.getenv("SHARED_CACHE_DB", "/tmp/blm_shared_cache.db")
                _shared_cache = SQLiteCache(cache_db_path)
                logger.info("SQLite shared cache initialized at %s", cache_db_path)
    return _shared_cache
```

### 9.2 Add Cache-Control Response Headers

```python
from fastapi.responses import JSONResponse

def _json_response(data: object, max_age: int) -> JSONResponse:
    response = JSONResponse(content=data)
    response.headers["Cache-Control"] = f"public, max-age={max_age}"
    return response
```

| Endpoint | TTL | Cache-Control |
|---|---|---|
| `bulk-deals` | 600s | `public, max-age=600` |
| `block-deals` | 600s | `public, max-age=600` |
| `high-short-interest` | 600s | `public, max-age=600` |
| `largedeal-snapshot` | 600s | `public, max-age=600` |
| `change-ranges` | 300s | `public, max-age=300` |
| `symbol-data` | 60s | `public, max-age=60` |
| `52week-low` | 10800s | `public, max-age=10800` |
| `52week-high` | 10800s | `public, max-age=10800` |
| `volume-gainers` | 1500s | `public, max-age=1500` |

### 9.3 Parallelize Background Workers

```python
async def _fetch_symbols_parallel(
    symbols: list[str],
    concurrency: int = 5,
    delay: float = 1.0,
) -> None:
    sem = asyncio.Semaphore(concurrency)

    async def fetch_one(symbol: str) -> None:
        async with sem:
            try:
                # ... existing fetch logic ...
                await asyncio.sleep(delay)
            except Exception:
                logger.debug("fetch_one: failed for %s", symbol)

    await asyncio.gather(
        *[fetch_one(s) for s in symbols],
        return_exceptions=True,
    )
```

---

## 10. Impact Estimates

### 10.1 Latency Reduction by Endpoint

| Endpoint | Before (avg) | After Phase 1 | After Phase 2 | After Phase 3 |
|---|---|---|---|---|
| `top-gainers` (cache miss) | 8,000ms | 2,500ms | 500ms | 300ms |
| `top-losers` (cache miss) | 8,000ms | 2,500ms | 500ms | 300ms |
| `symbol-data/XYZ` (cache miss) | 8,000ms | 1,500ms | 400ms | 200ms |
| `bulk-deals/XYZ` (cache miss) | 6,000ms | 1,500ms | 400ms | 200ms |
| `block-deals/XYZ` (cache miss) | 6,000ms | 1,500ms | 400ms | 200ms |
| `high-short-interest` (cache miss) | 6,000ms | 1,500ms | 300ms (one snapshot call, not three) | 200ms |
| `largedeal-snapshot` (cache miss) | 5,000ms | 2,000ms | 300ms (one call instead of three) | 200ms |
| `52week-high` (cache miss) | 5,000ms | 2,000ms | 500ms | 300ms |
| News crawl (6 pages) | 30,000ms | 6,000ms | 6,000ms | 3,000ms |
| Screener company | 4,000ms | 2,000ms | 2,000ms | 1,000ms |
| All cache hits | <50ms | <50ms | <50ms | <50ms |

### 10.2 Throughput Improvements

| Metric | Before | After Phase 1 | After Phase 2 |
|---|---|---|---|
| Concurrent NSE requests possible | 1 | 2 | 2 |
| NSE requests/minute (theoretical) | 30 | 60 | 60 |
| News crawl TCP connections | 120+ | 3-5 (reused) | 3-5 |
| Thread pool threads blocked by NSE | Up to 40 | 0 (async) | 0 |
| httpx clients created per news crawl | 120+ | 1 | 1 |
| In-flight request deduplication | None | Yes | Yes |
| Circuit breaker (fail-fast) | None | Yes (OPEN only) | Yes (OPEN + HALF_OPEN recovery) |

---

## 11. Testing & Verification Plan

### 11.1 Load Testing

```python
# backend/tests/test_load.py (example with locust)
from locust import HttpUser, task, between

class BLMTerminalUser(HttpUser):
    wait_time = between(1, 3)
    
    @task(5)
    def get_top_gainers(self):
        self.client.get("/api/market/top-gainers")
    
    @task(3)
    def get_symbol_data(self):
        for sym in ["RELIANCE", "INFY", "TCS", "HDFCBANK", "ICICIBANK"]:
            self.client.get(f"/api/market/symbol-data/{sym}")
    
    @task(2)
    def get_bulk_deals(self):
        for sym in ["RELIANCE", "INFY", "TCS"]:
            self.client.get(f"/api/market/bulk-deals/{sym}")
    
    @task(1)
    def news_global(self):
        self.client.get("/api/news/global")
```

```bash
locust -f tests/test_load.py --headless -u 10 -r 2 -t 60s --host http://localhost:8000
```

### 11.2 Benchmarking Script

```python
# backend/tests/bench_nse.py
import asyncio
import time
import httpx

BASE = "http://localhost:8000"

async def benchmark_endpoint(client: httpx.AsyncClient, path: str, runs: int = 5) -> dict:
    for _ in range(1):  # warmup
        await client.get(f"{BASE}{path}")
        await asyncio.sleep(1)

    times = []
    for _ in range(runs):
        t0 = time.perf_counter()
        resp = await client.get(f"{BASE}{path}")
        elapsed = (time.perf_counter() - t0) * 1000
        times.append(elapsed)
        print(f"  {path}: {elapsed:.0f}ms (status={resp.status_code})")
        await asyncio.sleep(0.5)

    return {"path": path, "avg_ms": sum(times) / len(times), "min_ms": min(times), "max_ms": max(times)}

async def main():
    async with httpx.AsyncClient(timeout=60.0) as client:
        endpoints = [
            "/api/market/top-gainers",
            "/api/market/top-losers",
            "/api/market/symbol-data/RELIANCE",
            "/api/market/bulk-deals/RELIANCE",
            "/api/market/high-short-interest",
            "/api/market/52week-high",
            "/api/market/largedeal-snapshot",
        ]
        results = await asyncio.gather(*[benchmark_endpoint(client, p) for p in endpoints])
        print("\n=== SUMMARY ===")
        for r in results:
            print(f"{r['path']}: avg={r['avg_ms']:.0f}ms min={r['min_ms']:.0f}ms max={r['max_ms']:.0f}ms")

if __name__ == "__main__":
    asyncio.run(main())
```

### 11.3 Existing Test Suite

```bash
pytest -m "not slow"
pytest --durations=10
pytest tests/test_endpoints.py -v
```

### 11.4 Verification Checklist

After each phase, verify:

- [ ] All existing tests pass (`pytest -m "not slow"`)
- [ ] `/health` endpoint responds < 50ms
- [ ] `/api/market/top-gainers` (cache miss) responds < 3,000ms (Phase 1) / < 800ms (Phase 2)
- [ ] `/api/market/symbol-data/RELIANCE` (cache miss) responds < 2,000ms (Phase 1) / < 500ms (Phase 2)
- [ ] News crawl completes without creating > 5 httpx clients (log should show "persistent httpx client" once)
- [ ] No `429 Too Many Requests` responses from NSE India
- [ ] Memory usage stays stable over 1-hour load test
- [ ] Circuit breaker: after 5 consecutive NSE failures, subsequent requests fail immediately (log: "Circuit breaker is OPEN")
- [ ] Circuit breaker recovery: 60s after circuit opens, next request logs "Circuit breaker HALF_OPEN — allowing probe request"
- [ ] Request coalescing: simultaneous requests log "Coalescing request" for all but the first
- [ ] Shared snapshot: calling bulk-deals, block-deals, and high-short simultaneously should fire only 1 NSE upstream call

---

## 12. Risk Assessment

### 12.1 Phase 1 Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| NSE rate limiting increases (2 concurrent instead of 1) | Medium | High | Keep courtesy delay. Monitor logs for 429s. |
| NewsFetcher client loop mismatch | Low | Medium | `init()` called in lifespan inside event loop. |
| MCP server breaks after removing its local `_nse_lock` | Low | High | Test all MCP endpoints after changes. |

### 12.2 Phase 2 Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| NSE API URLs change (breaking) | Low | High | URLs stable for years. nsepython fallback in top_gainers/top_losers. |
| Removing nsepython breaks other code paths | Low | Medium | Check `pyproject.toml` consumers. Keep during transition. |

### 12.3 Phase 3 Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| cachetools LRU eviction causes thrashing | Low | Low | Monitor hit rates. Increase maxsize. |
| SQLite shared cache write contention (multi-worker) | Medium | Medium | WAL mode handles concurrent reads during writes. |

---

## 13. Recommended Startup Configuration

### 13.1 ⚠️ CRITICAL: Workers and Shared State

| Config | Semaphores | Caches | Request Coalescing | Notes |
|---|---|---|---|---|
| `--workers 1` | ✓ Shared | ✓ Shared | ✓ Works | **Recommended for this project** |
| `--workers 4` | ✗ 4 independent | ✗ 4 cold-start | ✗ No dedup | Breaks everything in this doc |
| `--workers 4 + SQLite cache` | ✗ 4 independent | ✓ Shared | ✗ No dedup | Semaphores still broken |
| `--workers 4 + Redis` | ✓ Redis distributed | ✓ Redis | ✓ Redis | Full multi-worker support |

**For a single-user single-machine deployment: use `--workers 1`.**

### 13.2 Recommended Uvicorn Command

```bash
cd backend

# Install uvloop for 2-4× faster event loop
pip install uvloop

# Single worker + uvloop — all optimizations work correctly
uvicorn main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --loop uvloop \
  --workers 1 \
  --limit-concurrency 100 \
  --limit-max-requests 10000 \
  --timeout-keep-alive 30 \
  --log-config None
```

| Flag | Why |
|---|---|
| `--loop uvloop` | 2-4× faster event loop for I/O-heavy workloads |
| `--workers 1` | Required for all in-memory state (semaphores, caches, coalescing) to work |
| `--limit-concurrency 100` | Prevents thread-pool/executor exhaustion |
| `--limit-max-requests 10000` | Worker recycling prevents memory leaks |
| `--timeout-keep-alive 30` | Prevents hanging idle connections |

### 13.3 Environment Variables

```bash
# === Performance tuning (Phase 1) ===
NSE_CONCURRENCY=2
NSE_COURTESY_DELAY=1.5
SCREENER_CONCURRENCY=2

# === Phase 2: Async NSE ===
USE_ASYNC_NSE=false
NSE_CIRCUIT_FAIL_MAX=5
NSE_CIRCUIT_RESET_TIMEOUT=60

# === Phase 3: Shared cache (multi-worker future) ===
SHARED_CACHE_DB=/tmp/blm_shared_cache.db

# === News fetcher ===
NEWS_CRAWL_PAGES=6
NEWS_ARTICLE_CONCURRENCY=3

# === Logging ===
LOG_LEVEL=INFO
```

### 13.4 Multi-Worker Upgrade Path

**Step 1:** Switch from in-process to SQLite shared cache (already implemented in `cache.py`):
```python
from app.services.cache import get_shared_cache
shared = get_shared_cache()
```

**Step 2:** Replace in-memory semaphores with Redis distributed locks:
```python
import redis.asyncio as redis
_redis = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"))
```

**Step 3:** Run with workers:
```bash
uvicorn main:app --workers 4 --loop uvloop ...
```

### 13.5 Production Recommendations

1. **PostgreSQL for shared cache** — SQLite works for single-machine; PostgreSQL (via `asyncpg`) is better for horizontal scale
2. **OpenTelemetry tracing** — measure where time is spent per request
3. **Per-client-IP rate limiting** via `slowapi`:
   ```python
   from slowapi import Limiter
   limiter = Limiter(key_func=get_remote_address)
   app.state.limiter = limiter
   
   @app.get("/api/market/top-gainers")
   @limiter.limit("60/minute")
   async def top_gainers(request: Request): ...
   ```

---

## Appendix A: NSE API Direct URL Reference

| Purpose | URL | Method | Notes |
|---|---|---|---|
| Cookie warmup | `https://www.nseindia.com/` | GET | Establishes session cookies |
| Top gainers/losers | `https://www.nseindia.com/api/live-analysis-market-turnover` | GET | JSON with equity-wise data |
| 52-week low | `https://www.nseindia.com/api/live-analysis-data-52weeklowstock` | GET | Returns `{"data": [...]}` |
| 52-week high | `https://www.nseindia.com/api/live-analysis-data-52weekhighstock` | GET | Returns `{"data": [...]}` |
| Volume gainers | `https://www.nseindia.com/api/live-analysis-volume-gainers` | GET | Returns `{"data": [...]}` |
| Largedeals (all 3) | `https://www.nseindia.com/api/snapshot-capital-market-largedeal` | GET | BULK_DEALS_DATA + BLOCK_DEALS_DATA + SHORT_DEALS_DATA in one call |
| Symbol data | `https://www.nseindia.com/api/NextApi/apiClient/GetQuoteApi?functionName=getSymbolData&marketType=N&series=EQ&symbol={SYMBOL}` | GET | Per-symbol metadata |
| Change ranges | `https://www.nseindia.com/api/NextApi/apiClient/GetQuoteApi?functionName=getYearwiseData&symbol={SYMBOL}EQN` | GET | Historical % changes |
| Stock list | `https://www.nseindia.com/api/market-data-premium` | GET | All equity symbols |
| Corporate filings | `https://www.nseindia.com/api/annual-reports/detailed-result?symbol={SYMBOL}` | GET | Quarterly/annual results JSON |

---

## Appendix B: httpx Tuning Reference

```python
client = httpx.AsyncClient(
    base_url="https://api.example.com",
    timeout=httpx.Timeout(connect=10.0, read=20.0, write=10.0, pool=10.0),
    limits=httpx.Limits(
        max_connections=20,
        max_keepalive_connections=10,
        keepalive_expiry=30.0,
    ),
    transport=httpx.AsyncHTTPTransport(retries=3),
    verify=True,
    follow_redirects=True,
    headers={
        "User-Agent": "Mozilla/5.0 ...",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
    },
)
```

---

*End of Document*
