# UI Developer Handoff — News API Integration

This document explains how to integrate the news APIs into the BLM Terminal frontend.

---

## Base URL

The Next.js frontend proxies requests to the Python backend:

- **Backend runs on:** `http://localhost:4455`
- **Next.js proxy prefix:** `/api/py/` → `http://localhost:4455/api/`

So from the frontend, use paths like `/api/py/news/company/INFY`.

---

## API Endpoints

### 1. Get Company News (auto-fetch)

**Endpoint:** `POST /api/py/news/company`

Fetches fresh news for a company symbol and returns the stored articles.

**Request body:**
```typescript
{
  symbol: string;      // NSE ticker, e.g. "INFY", "RELIANCE", "TITAN"
  mc_url?: string;    // optional — auto-resolved if omitted
}
```

**Response:**
```typescript
type NewsArticle = {
  url: string;
  title: string | null;
  text: string | null;
  publish_date: string | null;  // ISO 8601
  fetched_at: string | null;    // ISO 8601
  company_symbol: string | null;
  source: string | null;
  top_image: string | null;
  authors: string | null;
}[]

// Example response:
[
  {
    "url": "https://www.moneycontrol.com/news/...",
    "title": "Stocks to Watch Today: Infosys, Waaree Renewable...",
    "text": "...",
    "publish_date": "2026-03-14T10:00:00",
    "fetched_at": "2026-03-14T12:00:00",
    "company_symbol": "INFY",
    "source": "moneycontrol_company",
    "top_image": "https://.../image.jpg",
    "authors": ["Moneycontrol Team"]
  },
  ...
]
```

**Frontend example:**
```typescript
async function fetchCompanyNews(symbol: string) {
  const response = await fetch('/api/py/news/company', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ symbol })
  });
  return response.json();
}
```

---

### 2. Get Cached Company News

**Endpoint:** `GET /api/py/news/company/{symbol}`

Returns already-stored articles for a symbol. Returns 404 if no articles exist yet.

**Response:** Same as above, array of `NewsArticle`.

**Frontend example:**
```typescript
async function getCompanyNews(symbol: string) {
  const response = await fetch(`/api/py/news/company/${symbol}`);
  if (!response.ok) {
    if (response.status === 404) return [];  // no articles yet
    throw new Error('Failed to fetch news');
  }
  return response.json();
}
```

---

### 3. Get Global News

**Endpoint:** `GET /api/py/news/global`

Returns general market news from MoneyControl (not company-specific).

**Query parameters (optional):**
- `start_date` — ISO datetime (default: 7 days ago)
- `end_date` — ISO datetime (default: now)

**Response:** Array of `NewsArticle`.

---

## How It Works

### URL Auto-Resolution

When you call `POST /api/news/company` without providing `mc_url`, the backend automatically resolves it:

1. **Cache check** — Looks up `mc_url` in the `stock_universe` table
2. **API resolution** — Calls MoneyControl's autocomplete API to get the stock page URL
3. **Fallback** — Uses a hardcoded map for known symbols (RELIANCE, INFY, TCS, HDFCBANK, etc.)

The resolved URL is cached in the database for future requests.

### Staleness

The backend tracks when articles were last fetched via the `fetched_at` field. The MCP tool (`get_company_news`) automatically re-fetches if the data is older than 5 minutes.

For the REST API, you can force a refresh by calling `POST /api/news/company` again — it will fetch fresh articles regardless of staleness.

---

## Integration Tips

### 1. First call triggers fetch

The first time you request news for a symbol, it will take longer (3-10 seconds) because the backend needs to:
- Resolve the MoneyControl URL (if not cached)
- Fetch the company's news page
- Parse and store each article

Subsequent calls return cached data instantly.

### 2. Handle 404 on GET

```typescript
const articles = await getCompanyNews(symbol);
if (articles.length === 0) {
  // No articles yet — trigger a fetch
  await fetchCompanyNews(symbol);
}
```

### 3. Polling for updates

To keep news fresh, you can poll periodically:

```typescript
setInterval(async () => {
  const articles = await fetchCompanyNews('INFY');  // POST triggers fresh fetch
  updateNewsUI(articles);
}, 5 * 60 * 1000);  // every 5 minutes
```

### 4. Error handling

```typescript
try {
  const articles = await fetchCompanyNews(symbol);
  displayNews(articles);
} catch (err) {
  console.error('Failed to fetch news:', err);
  showError('Unable to load news. Please try again.');
}
```

---

## MCP Tool (Alternative)

The backend also exposes a `get_company_news` MCP tool that can be used if you're using the MCP protocol:

```typescript
// Via MCP protocol (if configured)
const articles = await mcpClient.callTool('get_company_news', {
  symbol: 'INFY',
  days: 30,
  limit: 50,
  refresh: false
});
```

This tool automatically handles caching and staleness — it's what the terminal uses internally.

---

## Testing

```bash
# Test via curl
curl -X POST http://localhost:4455/api/news/company \
  -H "Content-Type: application/json" \
  -d '{"symbol": "INFY"}'

# Or via Next.js proxy
curl -X POST http://localhost:3000/api/py/news/company \
  -H "Content-Type: application/json" \
  -d '{"symbol": "TITAN"}'
```

---

## Supported Symbols

Any NSE symbol works — the autocomplete API resolves URLs for all Indian stocks. Examples:

- `RELIANCE`, `INFY`, `TCS`, `HDFCBANK`, `ICICIBANK`
- `SBIN`, `BAJFINANCE`, `MARUTI`, `TATASTEEL`, `WIPRO`
- `TITAN`, `ADANI`, `LIC`, `ONGC`, `COALINDIA`, etc.

---

## Response Fields Reference

| Field | Type | Description |
|-------|------|-------------|
| `url` | string | Full article URL on MoneyControl |
| `title` | string \| null | Article headline |
| `text` | string \| null | Full article body text |
| `publish_date` | string \| null | Publication timestamp (ISO 8601) |
| `fetched_at` | string \| null | When the article was fetched/cached |
| `company_symbol` | string \| null | NSE symbol this article is tagged with |
| `source` | string \| null | Either `moneycontrol_global` or `moneycontrol_company` |
| `top_image` | string \| null | URL of the featured image |
| `authors` | string \| null | Author name(s), comma-separated |
