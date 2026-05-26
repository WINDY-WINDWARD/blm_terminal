# Context Document - Multi-Source News System

**Project:** BLM Terminal Enhancement
**Branch:** `feature/multi-source-news`
**Last Updated:** 2026-05-27

---

## Why These Decisions Were Made

---

## 1. Why 35+ RSS Sources Instead of MoneyControl Only?

**Decision:** Add 35+ RSS feeds from global financial media

**Rationale:**
- Current BLM Terminal only uses MoneyControl for news
- FinceptTerminal has 80+ RSS feeds demonstrating scalability
- Users need global market perspective, not just India-focused news
- RSS is reliable, standardized, and easy to parse

**Challenges Faced:**
- Different RSS feeds have different formats (RSS 2.0, Atom, mixed)
- Some feeds are unreliable or have moved
- Rate limiting considerations for multiple concurrent fetches
- Solution: Use `feedparser` library for unified parsing, stagger requests

---

## 2. Why Keep MoneyControl Scraping AND Add RSS?

**Decision:** Keep existing `news_fetcher.py` MoneyControl scraping AND add RSS feeds

**Rationale:**
- MoneyControl RSS only provides headlines/summaries
- MoneyControl scraping (`news_fetcher.py`) provides full article text, authors, images
- RSS and scraping serve different purposes:
  - RSS = real-time headlines (fast, multiple sources)
  - Scraping = detailed company-specific news (deeper)
- User chose "Keep both" option

**Challenges Faced:**
- Potential duplicate articles if both sources have same news
- Solution: URL-based deduplication in database, different source flags

---

## 3. Why Keep NSE Announcements Separate?

**Decision:** Leave `announcements.py` untouched - it's NOT part of news

**Rationale:**
- NSE Announcements (`/announcements`, `/event-calendar`) are corporate event data
  - Board meetings, earnings announcements, AGM notices, board results
  - NOT news articles or market commentary
- Completely different data type and use case
- User explicitly clarified this should stay separate

**Challenges Faced:**
- Initial plan accidentally included "NSE Announcements" as Tier 2 India source
- Had to clarify with user that this is different data
- Solution: Remove from news scope, leave in `announcements.py`

---

## 4. Why Alembic for Migrations?

**Decision:** Use SQLAlchemy Alembic for database migrations

**Rationale:**
- BLM Terminal already uses SQLAlchemy for news model
- Alembic provides versioned, reversible migrations
- Better than manual SQLite ALTER TABLE statements
- User confirmed "Alembic (Recommended)"

**Challenges Faced:**
- Initial preference was for simplicity (manual SQLite)
- But Alembic is more maintainable for tracking schema changes
- Solution: Use Alembic as recommended

---

## 5. Why Simple WebSocket Architecture?

**Decision:** Single WebSocket connection, no Redis/pubsub

**Rationale:**
- This is a single-user local desktop app
- Each user has their own installation
- No need for scalable pub/sub infrastructure
- User confirmed "Few (< 10)" connections expected

**Challenges Faced:**
- FinceptTerminal uses more complex multi-client architecture
- But that's a server-deployed app, BLM Terminal is local-first
- Solution: Simplified architecture appropriate for local app

---

## 6. Why New Articles Only for NLP?

**Decision:** NLP processing for new articles only, no historical backfill

**Rationale:**
- User chose "New articles only"
- Historical backfill would be computationally expensive
- Existing articles don't have NLP fields anyway
- Lazy backfill available on-demand if needed

**Challenges Faced:**
- Question: What about existing 1000s of articles in database?
- Solution: They remain without NLP fields, new articles get NLP
- On-demand analysis available via `/news/analyze` endpoint

---

## 7. Why Weighted Word Lists for NLP?

**Decision:** Use simple weighted word lists instead of ML/NLTK

**Rationale:**
- Same approach as FinceptTerminal (rule-based)
- No external NLP library dependencies
- Fast, predictable, no training required
- Good enough for headline-level sentiment

**Challenges Faced:**
- Simple approach may miss context/sarcasm
- But headlines are typically straightforward
- Solution: Weighted lists + confidence scores for uncertainty

---

## 8. Why Replace MoneyControl Scraping with RSS?

**Decision:** Don't replace - add RSS alongside existing scraping

**Rationale:**
- RSS provides fast, multiple sources
- Scraping provides detailed article content
- Both are valuable
- User chose "Keep both (Recommended)"

**Challenges Faced:**
- Confusion on whether to deprecate scraping
- User clarification resolved this
- Solution: Both coexist, different purposes

---

## 9. Why India Sources Limited to 4?

**Decision:** MoneyControl, Economic Times, LiveMint, The Hindu Business

**Rationale:**
- These are the major India-focused financial news RSS feeds
- Business Standard, Financial Express have less reliable RSS
- Bloomberg Quint India RSS is good addition
- User chose "Include all"

**Challenges Faced:**
- Not all Indian news sources have working RSS feeds
- Some require authentication
- Solution: Include verified working RSS feeds only

---

## 10. Why 35+ Sources When User Said "Financial + India Focus"?

**Decision:** Include global financial sources + India sources

**Rationale:**
- "Financial + India focus" means prioritize India but include global
- Global financial news affects Indian markets
- Users need context of global events
- Sources chosen: Bloomberg, WSJ, CNBC (global) + MC, ET, LiveMint (India)

**Challenges Faced:**
- Balancing scope creep vs comprehensive coverage
- Solution: Tier system (Tier 1 = most important, Tier 3 = supplementary)

---

## 11. Why Tiers for Sources?

**Decision:** Tier 1 (trusted), Tier 2 (standard), Tier 3 (supplementary)

**Rationale:**
- Different reliability/authoritativeness of sources
- Wire services (AP, Reuters) = Tier 1
- Major financial (Bloomberg, WSJ) = Tier 1
- Secondary (blogs, aggregators) = Tier 3
- Helps with credibility scoring and filtering

**Challenges Faced:**
- Some sources don't fit neatly into tiers
- Solution: Manual classification based on reputation

---

## 12. Why WebSocket Instead of Polling?

**Decision:** Add WebSocket for real-time news delivery

**Rationale:**
- User chose "WebSocket (real-time)"
- Polling every 5 minutes is not real-time
- WebSocket provides instant delivery when new articles arrive
- Single-user app = simple WebSocket sufficient

**Challenges Faced:**
- Existing BLM Terminal uses polling for news
- Adding WebSocket is new infrastructure
- Solution: WebSocket + polling fallback

---

## Reference: FinceptTerminal vs BLM Terminal

| Aspect | FinceptTerminal | BLM Terminal |
|--------|-----------------|--------------|
| Language | C++ + Python | Python + TypeScript |
| News Sources | 80+ RSS (C++) | 1 scraping (MoneyControl) |
| NLP | Full pipeline | None |
| WebSocket | Yes | No (polling) |
| Database | Qt Sql + SQLite | SQLAlchemy + Prisma |
| Architecture | Server/desktop | Local desktop |

**BLM Terminal is simpler** - we're adding multi-source RSS and NLP without changing the fundamental architecture.
