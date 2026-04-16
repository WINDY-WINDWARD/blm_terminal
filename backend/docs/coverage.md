Endpoints/Features Missing from MCP Server
1. ticker.py — All 16 endpoints (entire router absent)
Endpoint
GET /api/ticker/ohlcv/{symbol}
GET /api/ticker/ohlcv/{symbol}/latest
GET /api/ticker/status
POST /api/ticker/trigger-backfill
POST /api/ticker/trigger-daily-update
GET /api/ticker/returns/{symbol}
GET /api/ticker/returns-bulk
GET /api/ticker/universe-returns
GET /api/ticker/sector-returns
GET /api/ticker/position/52w/{symbol}
GET /api/ticker/momentum-score/{symbol}
GET /api/ticker/momentum-leaderboard
GET /api/ticker/indicators/{symbol}
GET /api/ticker/streaks/{symbol}
GET /api/ticker/screener
2. ai_summarizer.py
Endpoint
POST /api/ai/summarize
GET /api/ai/health
3. corporatefilings.py
Endpoint
GET /api/corporatefilings/{symbol}
4. morningstar.py
Endpoint
GET /api/morningstar/fairvalue/{symbol}
GET /api/morningstar/search
5. jobs.py — Entire router absent
Endpoint
GET /api/jobs
GET /api/jobs/{job_key}
POST /api/jobs/{job_key}/trigger
POST /api/jobs/{job_key}/toggle
POST /api/jobs/sync
6. notifications.py — Entire router absent
Endpoint
GET /api/notifications
DELETE /api/notifications/{notif_id}
DELETE /api/notifications
GET /api/notifications/global
DELETE /api/notifications/global/{notif_id}
DELETE /api/notifications/global
POST /api/notifications/trigger
7. watchlist.py — Multi-watchlist CRUD absent (only legacy single-watchlist is wrapped)
Endpoint
GET /api/watchlists
POST /api/watchlists
DELETE /api/watchlists/{watchlist_id}
GET /api/watchlists/{watchlist_id}/items
POST /api/watchlists/{watchlist_id}/items
DELETE /api/watchlists/{watchlist_id}/items/{item_id}
8. stockuniverse.py — Admin/management endpoints absent
Endpoint
POST /api/stockuniverse/run-mc-linker
GET /api/stockuniverse/pending-review
PUT /api/stockuniverse/{symbol}/confirm-match
---
Summary: The MCP server covers the core market data, screener, news, markets, and basic single-watchlist operations. Missing are the entire ticker analytics suite (biggest gap — 16 endpoints), notifications, multi-watchlist management, AI summarizer, Morningstar, corporate filings, jobs management, and stock universe admin tools.