# Multi-Source News System - Implementation Plan

**Project:** BLM Terminal Enhancement
**Branch:** `feature/multi-source-news`
**Status:** PLANNING
**Last Updated:** 2026-05-27

---

## Overview

Replace the single-source MoneyControl news system with a multi-source RSS aggregation system that pulls from 35+ global and India-focused news sources, adds NLP processing (sentiment, entities, threat classification), and delivers real-time updates via WebSocket.

---

## Scope

### In Scope
- [x] Multi-source RSS feed aggregation (35+ sources)
- [x] NLP processing pipeline (sentiment, entities, threat classification)
- [x] Real-time WebSocket delivery
- [x] Enhanced frontend UI with filtering and indicators
- [x] Alembic database migrations
- [x] India-specific sources (MoneyControl, Economic Times, LiveMint, The Hindu Business)

### Out of Scope
- [x] NSE Announcements - kept separate in `announcements.py` (corporate event data, not news)
- [x] MoneyControl scraping - kept in `news_fetcher.py` (company-specific detailed news)
- [x] Historical NLP backfill - new articles only

---

## Feed Sources (35+ Sources)

### Tier 1 - Wire Services & Regulators (5)

| ID | Name | URL | Category |
|----|------|-----|----------|
| `ap-top` | AP Top News | `https://rsshub.app/apnews/topics/ap-top-news` | GEOPOLITICS |
| `sec-press` | SEC Press | `https://www.sec.gov/news/pressreleases.rss` | REGULATORY |
| `fed-press` | Federal Reserve | `https://www.federalreserve.gov/feeds/press_all.xml` | REGULATORY |
| `ecb-press` | ECB Press | `https://www.ecb.europa.eu/rss/press.html` | REGULATORY |
| `boe-news` | Bank of England | `https://www.bankofengland.co.uk/rss/news` | REGULATORY |

### Tier 1 - Major Financial (3)

| ID | Name | URL | Category |
|----|------|-----|----------|
| `bloomberg-mkts` | Bloomberg Markets | `https://feeds.bloomberg.com/markets/news.rss` | MARKETS |
| `wsj-markets` | WSJ Markets | `https://feeds.a.dj.com/rss/RSSMarketsMain.xml` | MARKETS |
| `cnbc-finance` | CNBC Finance | `https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114` | MARKETS |

### Tier 2 - India (4)

| ID | Name | URL | Category |
|----|------|-----|----------|
| `moneycontrol` | MoneyControl | `https://www.moneycontrol.com/rss/latestnews.xml` | MARKETS |
| `et-markets` | Economic Times | `https://economictimes.indiatimes.com/rssfeedstopstories.cms` | MARKETS |
| `livemint` | LiveMint | `https://www.livemint.com/rss/markets` | MARKETS |
| `hindu-biz` | The Hindu Business | `https://www.thehindu.com/business/feeder/default.rss` | MARKETS |

### Tier 2 - Global (10)

| ID | Name | URL | Category |
|----|------|-----|----------|
| `marketwatch` | MarketWatch | `https://feeds.marketwatch.com/marketwatch/topstories/` | MARKETS |
| `seekingalpha` | Seeking Alpha | `https://seekingalpha.com/market_currents.xml` | MARKETS |
| `investing-news` | Investing.com | `https://www.investing.com/rss/news.rss` | MARKETS |
| `benzinga` | Benzinga | `https://www.benzinga.com/feed` | MARKETS |
| `bbc-business` | BBC Business | `http://feeds.bbci.co.uk/news/business/rss.xml` | MARKETS |
| `nikkei-asia` | Nikkei Asia | `https://asia.nikkei.com/rss/feed/nar` | MARKETS |
| `cna` | Channel News Asia | `https://www.channelnewsasia.com/rssfeeds/8395986` | MARKETS |
| `economist` | The Economist | `https://www.economist.com/finance-and-economics/rss.xml` | ECONOMIC |
| `aljazeera` | Al Jazeera | `https://www.aljazeera.com/xml/rss/all.xml` | GEOPOLITICS |
| `foreignpolicy` | Foreign Policy | `https://foreignpolicy.com/feed/` | GEOPOLITICS |

### Tier 2 - Crypto (3)

| ID | Name | URL | Category |
|----|------|-----|----------|
| `coindesk` | CoinDesk | `https://www.coindesk.com/arc/outboundfeeds/rss/` | CRYPTO |
| `cointelegraph` | CoinTelegraph | `https://cointelegraph.com/rss` | CRYPTO |
| `theblock` | The Block | `https://www.theblock.co/rss.xml` | CRYPTO |

### Tier 2 - Tech (4)

| ID | Name | URL | Category |
|----|------|-----|----------|
| `techcrunch` | TechCrunch | `https://techcrunch.com/feed/` | TECH |
| `finextra` | Finextra | `https://www.finextra.com/rss/headlines.aspx` | TECH |
| `theverge` | The Verge | `https://www.theverge.com/rss/index.xml` | TECH |
| `arstechnica` | Ars Technica | `https://feeds.arstechnica.com/arstechnica/index` | TECH |

### Tier 3 - Additional (6)

| ID | Name | URL | Category |
|----|------|-----|----------|
| `bbc-world` | BBC World | `http://feeds.bbci.co.uk/news/world/rss.xml` | GEOPOLITICS |
| `calculated-risk` | Calculated Risk | `https://feeds.feedburner.com/CalculatedRisk` | ECONOMIC |
| `zero-hedge` | ZeroHedge | `https://feeds.feedburner.com/zerohedge/feed` | ECONOMIC |
| `bellingcat` | Bellingcat | `https://www.bellingcat.com/feed/` | GEOPOLITICS |
| `hackernews` | Hacker News | `https://hnrss.org/frontpage` | TECH |
| `abnormal-returns` | Abnormal Returns | `https://abnormalreturns.com/feed/` | MARKETS |

---

## NLP Processing

### Sentiment Analysis
```
POSITIVE_WORDS = {
    "surge": 3, "soar": 3, "skyrocket": 3, "breakthrough": 3, "boom": 3,
    "rally": 2, "gain": 2, "rise": 2, "jump": 2, "climb": 2,
    "rebound": 2, "boost": 2, "beat": 2, "exceed": 2, "upgrade": 2,
    "profit": 2, "growth": 2, "recover": 2, "strong": 1, "robust": 1
}

NEGATIVE_WORDS = {
    "crash": 3, "plunge": 3, "collapse": 3, "devastat": 3,
    "invasion": 3, "bankruptcy": 3, "meltdown": 3,
    "fall": 2, "drop": 2, "decline": 2, "tumble": 2, "miss": 2,
    "fail": 2, "recession": 2, "crisis": 2, "attack": 2,
    "sanction": 2, "tariff": 2, "escalat": 2, "downgrade": 2
}

Returns: BULLISH/BEARISH/NEUTRAL + score (-1 to 1) + confidence (0 to 1)
```

### Entity Extraction
- **Countries:** 70+ name-to-ISO-code mappings
- **Organizations:** 100+ patterns (NATO, UN, IMF, Fed, ECB, World Bank, etc.)
- **People:** Known leaders + title patterns (President, CEO, etc.)
- **Tickers:** Regex `\b[A-Z]{2,5}\b` filtered against common words

### Threat Classification
```python
CRITICAL: nuclear strike, market crash, flash crash, circuit breaker, bank run
HIGH: invasion, airstrike, missile launch, rate hike, bankruptcy, downgrade
MEDIUM: protest, tariff, recession, inflation, selloff, volatil
```

### Source Credibility
```python
STATE_MEDIA: XINHUA, CGTN, RT, TASS, SPUTNIK, PRESS TV, KCNA
CAUTION: ZEROHEDGE, INFOWARS, DAILY MAIL, NY POST
```

---

## Database Schema

### New Columns for `news_articles`

```python
# Source metadata
source_name: String(64)      # e.g., "BLOOMBERG"
source_tier: Integer         # 1, 2, 3
source_category: String(32)  # MARKETS, GEOPOLITICS, CRYPTO, TECH, REGULATORY
source_id: String(32)        # e.g., "bloomberg-mkts"

# NLP fields
sentiment: String(16)        # BULLISH, BEARISH, NEUTRAL
sentiment_score: Float       # -1.0 to 1.0
confidence: Float            # 0.0 to 1.0
language: String(8)          # en, zh, ja, ko, ru, ar, hi

# Entities
entities: JSON               # {"countries": [], "orgs": [], "people": [], "tickers": []}

# Threat
threat_level: String(16)     # CRITICAL, HIGH, MEDIUM, LOW
threat_category: String(32)  # conflict, market, cyber, natural, regulatory
priority: String(16)         # FLASH, URGENT, BREAKING, ROUTINE

# Credibility
source_credibility: String(16)  # STATE_MEDIA, CAUTION, NONE

# Location
location: JSON               # {"lat": float, "lon": float}
```

---

## API Routes

### Modified Endpoints

| Method | Endpoint | Changes |
|--------|----------|---------|
| GET | `/news/global` | Add NLP fields to response |
| GET | `/news/company/{symbol}` | Add NLP fields |
| POST | `/news/company` | Keep existing (MoneyControl scraping) |

### New Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/news/all` | Aggregated multi-source with filters |
| GET | `/news/sources` | List all configured sources |
| POST | `/news/analyze` | Analyze raw text for NLP |

### Query Parameters for `/news/all`
```
sources, categories, sentiment, threat_level, tickers, countries,
language, start_date, end_date, limit, offset
```

---

## Background Workers

| Worker | Schedule | Action |
|--------|----------|--------|
| `news_rss_worker` | `*/5 * * * *` | Fetch Tier 1 + Tier 2 RSS feeds |
| `news_tier3_worker` | `*/10 * * * *` | Fetch Tier 3 feeds |

**Existing workers (UNMODIFIED):**
- `news_worker` - MoneyControl scraping (company news)
- `watchlist_news_worker` - Watchlist company news
- NSE Announcements in `announcements.py`

---

## WebSocket

- **Endpoint:** `/ws/news`
- **Protocol:** JSON messages
- **Architecture:** Single connection (local single-user app)
- **Messages:**
  - Server → Client: `{ type: "news", article: {...} }`
  - Client → Server: `{ action: "subscribe", sources: [...] }`

---

## Frontend Changes

### Files to Modify

1. **`src/lib/socket.ts`** - Add news WebSocket client
2. **`src/store/terminalStore.ts`** - Add news atoms
3. **`src/components/widgets/NewsWidget.tsx`** - Enhanced UI

### UI Enhancements

- Source filter chips
- Sentiment indicator (color dot: green/red/yellow)
- Threat level badge
- Entity display (ticker chips)
- Credibility warning icon (state media/caution sources)
- "LIVE" indicator when WebSocket connected
- Real-time article insertion

---

## Implementation Order

```
1. backend/app/services/news_sources.py       # Define all 35+ feed sources
2. backend/app/services/rss_parser.py         # RSS parsing with feedparser
3. backend/app/services/nlp_service.py       # NLP (sentiment, entities, threat)
4. backend/app/services/news_aggregator.py    # Orchestration layer
5. backend/alembic/versions/xxxxx_*.py      # Migration for new fields
6. backend/app/models/news.py                # Add new fields to model
7. backend/app/routers/news.py              # Update/add routes
8. backend/app/backgroundtasks.py             # Add RSS workers
9. backend/app/websocket/news_ws.py          # WebSocket endpoint
10. src/lib/socket.ts                        # Add news WebSocket client
11. src/store/terminalStore.ts               # Add news atoms
12. src/components/widgets/NewsWidget.tsx     # Update UI
```

---

## Dependencies

**Backend:**
```
feedparser>=6.0.0
```

**Frontend:** No new dependencies (using existing React Query + Jotai)

---

## What's NOT Changing

| Component | File | Reason |
|-----------|------|--------|
| NSE Announcements | `announcements.py` | Corporate event data |
| Event Calendar | `announcements.py` | Different data type |
| MoneyControl Scraper | `news_fetcher.py` | Detailed company news |
| Database ORM | Prisma | Used for TopMoverSymbol, UserSettings only |
| News Model | SQLAlchemy | Used for news_articles |

---

## Acceptance Criteria

1. [ ] 35+ RSS feeds successfully fetch and parse
2. [ ] NLP processing adds sentiment, entities, threat to articles
3. [ ] WebSocket delivers new articles in real-time
4. [ ] Frontend displays multi-source news with filtering
5. [ ] Source credibility warnings display correctly
6. [ ] India sources (MoneyControl, ET, LiveMint, Hindu) included
7. [ ] Existing MoneyControl scraping still works
8. [ ] NSE Announcements remain separate
9. [ ] Alembic migration runs cleanly
10. [ ] All tests pass
