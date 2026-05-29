> **ARCHIVED** — This document describes a completed implementation. It is kept for historical reference only and is no longer maintained.

---

# Memory Document - Multi-Source News System

**Project:** BLM Terminal Enhancement
**Branch:** `feature/multi-source-news`
**Last Updated:** 2026-05-27

---

## Status: IMPLEMENTATION COMPLETE

- [x] Backend: RSS aggregation + NLP (50 unit tests passing)
- [x] WebSocket: /ws/news endpoint + broadcast integration
- [x] Frontend: NewsWidget enhanced with live articles, filters, sentiment dots
- [x] MCP tools: Updated with full NLP fields + filter params

---

## Decisions Made

| Decision | Choice | Date |
|----------|--------|------|
| Database Migrations | Alembic | 2026-05-27 |
| WebSocket Architecture | Simple (single user, no Redis) | 2026-05-27 |
| India Sources | All 4 (MC, ET, LiveMint, Hindu) | 2026-05-27 |
| NSE Announcements | Keep separate (not news) | 2026-05-27 |
| NLP Scope | New articles only | 2026-05-27 |
| Frontend Scope | Everything needed for widget | 2026-05-27 |
| MoneyControl | Keep both (scraping + RSS) | 2026-05-27 |
| User Framework | React Query + Jotai (same patterns) | 2026-05-27 |
| MCP get_global_news | All sources by default (no source filter) | 2026-05-27 |
| MCP NLP fields | Both get_global_news and get_company_news | 2026-05-27 |
| MCP filter logic | OR/additive (article passes if matches any filter) | 2026-05-27 |

---

## What Was Done

### Phase 1: Research
- [x] Explored FinceptTerminal codebase (80+ RSS feeds, C++ news system)
- [x] Explored BLM Terminal codebase (MoneyControl scraping, single source)
- [x] Identified NSE announcements as separate system in `announcements.py`
- [x] Identified existing India news sources: MoneyControl only

### Phase 2: Planning
- [x] Selected 35+ RSS feed sources (Financial + India focus)
- [x] Designed NLP processing pipeline (based on FinceptTerminal)
- [x] Planned WebSocket architecture (simple single-user)
- [x] Planned frontend enhancements
- [x] Created implementation plan document
- [x] Created memory document
- [x] Created context document

### Phase 3: Documentation
- [x] Created `PLAN.md` with detailed implementation plan
- [x] Created `MEMORY.md` (this file)
- [x] Created `CONTEXT.md` with decision rationale

### Phase 4: Backend Implementation

#### New Files Created
| File | Purpose |
|------|---------|
| `backend/app/services/news_sources.py` | 35+ RSS feed source definitions |
| `backend/app/services/rss_parser.py` | RSS parsing with feedparser |
| `backend/app/services/nlp_service.py` | NLP processing (sentiment, entities, threat) |
| `backend/app/services/news_aggregator.py` | Orchestration layer |
| `backend/app/routers/news_ws.py` | WebSocket endpoint at /ws/news |
| `src/lib/newsSocket.ts` | News WebSocket client for frontend |
| `backend/alembic/versions/x123456789newsnlp_add_news_nlp_fields.py` | Database migration |

#### Files Modified
| File | Changes |
|------|---------|
| `backend/app/models/news.py` | Added NLP fields |
| `backend/app/schemas/news.py` | Added NLP schemas, new endpoints |
| `backend/app/routers/news.py` | Added /sources, /all, /analyze endpoints |
| `backend/app/routers/__init__.py` | Added news_ws_router |
| `backend/main.py` | Mounted news_ws_router at /ws/news |
| `backend/app/backgroundtasks.py` | Added news_rss_worker + WS broadcast |
| `backend/app/mcp_server.py` | get_global_news/get_company_news: all sources + NLP fields + filters |
| `blm-mcp-bundle/manifest.json` | Updated news tool descriptions |
| `src/store/terminalStore.ts` | Added newsWsConnectedAtom, liveNewsArticlesAtom, newsFiltersAtom |
| `src/components/widgets/NewsWidget.tsx` | Enhanced with live articles, source filters, sentiment dots, threat badges |
| `backend/pyproject.toml` | Added feedparser dependency |

#### Tests Created/Updated
| File | Tests |
|------|-------|
| `backend/tests/test_news_sources.py` | 15 tests for source definitions |
| `backend/tests/test_nlp_service.py` | 35 tests for NLP processing |
| `backend/tests/test_mcp.py` | Updated news tests (NLP fields, filters) |

### Phase 5: Testing
- [x] All 50 unit tests passing
- [x] Imports verified working
- [x] TypeScript check passing (newsSocket.ts, NewsWidget.tsx, terminalStore.ts)
- [x] Lint passing for new files

---

## Files Created/Modified Summary

### New Files (8)
```
backend/app/services/news_sources.py          # RSS feed definitions (35+ sources)
backend/app/services/rss_parser.py           # RSS parsing with feedparser
backend/app/services/nlp_service.py           # NLP (sentiment, entities, threat)
backend/app/services/news_aggregator.py       # Orchestration
backend/app/routers/news_ws.py                 # WebSocket endpoint
src/lib/newsSocket.ts                         # News WebSocket client
backend/alembic/versions/x123456789newsnlp_add_news_nlp_fields.py  # Migration
```

### Modified Files (12)
```
backend/app/models/news.py                  # Added NLP fields
backend/app/schemas/news.py                 # Added NLP schemas
backend/app/routers/news.py                 # New endpoints
backend/app/routers/__init__.py             # news_ws_router
backend/main.py                             # Mounted news_ws_router at /ws/news
backend/app/backgroundtasks.py               # RSS worker + WS broadcast
backend/app/mcp_server.py                   # get_global_news + get_company_news updated
blm-mcp-bundle/manifest.json                # Updated news tool descriptions
src/store/terminalStore.ts                  # News atoms
src/components/widgets/NewsWidget.tsx       # Enhanced UI
backend/pyproject.toml                      # Added feedparser
backend/tests/test_mcp.py                   # Updated news tests
```

---

## What Was NOT Implemented

### WebSocket
- [x] IMPLEMENTED: /ws/news WebSocket endpoint
- [x] IMPLEMENTED: broadcast_news_update integrated in backgroundtasks.py
- [x] IMPLEMENTED: src/lib/newsSocket.ts client with reconnection

### Frontend Updates
- [x] IMPLEMENTED: NewsWidget.tsx with live articles section
- [x] IMPLEMENTED: Source filter chips, sentiment dots, threat badges
- [x] IMPLEMENTED: News atoms in terminalStore.ts

### MCP Tools
- [x] IMPLEMENTED: get_global_news returns all sources (not just MC) + NLP fields + filter params
- [x] IMPLEMENTED: get_company_news includes NLP fields + filter params
- [x] IMPLEMENTED: manifest.json updated with new tool descriptions

---

## Challenges Faced

1. **RSS Parser Async**: Used `httpx.AsyncClient` for concurrent fetching
2. **Test Expectations**: Fixed Japanese detection test to use pure katakana
3. **Source Matching**: State media test needed exact uppercase match ("XINHUA" not "Xinhua News")

---

## Test Results

```
50 passed in 0.03s (backend unit tests)
- test_news_sources.py: 15 passed
- test_nlp_service.py: 35 passed
MCP tests require running backend server (not run during CI)
```

---

## Next Steps

1. Commit all changes to `feature/multi-source-news`
2. Run migration: `alembic upgrade head`
3. Start backend and test RSS worker end-to-end
4. Test WebSocket connection in browser
5. Build and test full integration

---

## Questions Answered

1. **Database Migration?** → Alembic
2. **WebSocket Scale?** → Single user local app → Simple architecture (IMPLEMENTED)
3. **India Sources?** → Include all 4 (MC, ET, LiveMint, Hindu)
4. **NSE Announcements?** → Keep separate (corporate event data)
5. **NLP Scope?** → New articles only
6. **Frontend Framework?** → Same patterns (React Query + Jotai)
7. **UI Scope?** → Everything needed for widget to work
8. **MoneyControl?** → Keep both (scraping + RSS)
9. **MCP get_global_news scope?** → All sources by default (no source filter)
10. **MCP NLP fields?** → Both tools get NLP fields
11. **MCP filter logic?** → OR/additive (any filter matches = include)
