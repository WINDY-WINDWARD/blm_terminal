# Memory Document - Multi-Source News System

**Project:** BLM Terminal Enhancement
**Branch:** `feature/multi-source-news`
**Last Updated:** 2026-05-27

---

## Status: PLANNING PHASE COMPLETE

---

## Decisions Made

| Decision | Choice | Date |
|----------|--------|------|
| Database Migrations | Alembic | 2026-05-27 |
| WebSocket Scale | Single user (local app) | 2026-05-27 |
| India Sources | All 4 (MC, ET, LiveMint, Hindu) | 2026-05-27 |
| NSE Announcements | Keep separate (not news) | 2026-05-27 |
| NLP Scope | New articles only | 2026-05-27 |
| Frontend Scope | Everything needed for widget | 2026-05-27 |
| MoneyControl | Keep both (scraping + RSS) | 2026-05-27 |
| User Framework | React Query + Jotai (same patterns) | 2026-05-27 |

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
- [x] Created this memory document
- [x] Created context document

### Phase 3: Documentation
- [x] Created `PLAN.md` with detailed implementation plan
- [x] Created `MEMORY.md` (this file)
- [x] Created `CONTEXT.md` with decision rationale

---

## Files Created

| File | Purpose |
|------|---------|
| `docs/multi-source-news/PLAN.md` | Detailed implementation plan |
| `docs/multi-source-news/MEMORY.md` | What was done (this file) |
| `docs/multi-source-news/CONTEXT.md` | Why decisions were made |

---

## Pending Work (NOT STARTED)

### Backend
- [ ] `backend/app/services/news_sources.py` - Feed source definitions
- [ ] `backend/app/services/rss_parser.py` - RSS parsing
- [ ] `backend/app/services/nlp_service.py` - NLP processing
- [ ] `backend/app/services/news_aggregator.py` - Orchestration
- [ ] `backend/alembic/versions/xxxxx_add_news_source_nlp_fields.py` - Migration
- [ ] `backend/app/models/news.py` - Model updates
- [ ] `backend/app/routers/news.py` - Route updates
- [ ] `backend/app/backgroundtasks.py` - Worker updates
- [ ] `backend/app/websocket/news_ws.py` - WebSocket

### Frontend
- [ ] `src/lib/socket.ts` - WebSocket client
- [ ] `src/store/terminalStore.ts` - New atoms
- [ ] `src/components/widgets/NewsWidget.tsx` - UI enhancements

---

## Questions Answered

1. **Database Migration?** → Alembic
2. **WebSocket Scale?** → Single user local app
3. **India Sources?** → Include all 4 (MC, ET, LiveMint, Hindu)
4. **NSE Announcements?** → Keep separate (corporate event data)
5. **NLP Scope?** → New articles only
6. **Frontend Framework?** → Same patterns (React Query + Jotai)
7. **UI Scope?** → Everything needed for widget to work
8. **MoneyControl?** → Keep both (scraping + RSS)

---

## Next Steps

1. Review and approve plan
2. Start coding when approved
3. Follow implementation order in PLAN.md
