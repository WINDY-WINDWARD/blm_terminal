# Market Categories API - UI Developer Handoff

## Overview

New endpoints to access industry and sector data from MoneyControl, including:
- 189 industries
- 39 sectors  
- ~5,000 unique stocks with their categories

Data is refreshed during market hours (weekdays 9:15 AM - 3:30 PM IST) every 5 minutes.

---

## REST API Endpoints

### Base URL
```
http://localhost:4455/api
```

### 1. List All Industries

```http
GET /markets/industries
```

**Response:**
```json
[
  {
    "category_type": "industry",
    "slug": "bank-private",
    "name": "Bank - Private",
    "url": "https://www.moneycontrol.com/markets/industry-analysis/bank-private/",
    "market_cap": 3469105.0,
    "pe": 18.52,
    "advance": 2,
    "decline": 26,
    "sentiment": "Bearish",
    "earnings_yoy": 0.54,
    "last_updated": "2026-03-14T18:30:00",
    "created_at": "2026-03-14T12:00:00"
  },
  ...
]
```

### 2. List All Sectors

```http
GET /markets/sectors
```

**Response:** Same structure as industries, with 39 sectors.

### 3. Get Stocks in an Industry

```http
GET /markets/industries/{slug}/stocks
```

**Example:**
```http
GET /markets/industries/bank-private/stocks
```

**Response:**
```json
[
  {
    "id": 1695,
    "symbol": "HDF01",
    "company_name": "HDFC Bank",
    "exchange": "NSE",
    "curr_price": 817.0,
    "per_change": -1.89,
    "market_cap": 1257391.0,
    "ttm_pe": 16.88,
    "net_profit": 20691.0,
    "net_profit_yoy": 12.82,
    "tech_trend": "Very Bearish",
    "mc_url": "https://www.moneycontrol.com/india/stockpricequote/banks-private-sector/hdfcbank/HDF01",
    "categories": [
      {"type": "industry", "slug": "bank-private"},
      {"type": "sector", "slug": "banks"}
    ],
    "last_updated": "2026-03-14T18:30:00",
    "created_at": "2026-03-14T12:00:00"
  },
  ...
]
```

### 4. Get Stocks in a Sector

```http
GET /markets/sectors/{slug}/stocks
```

**Example:**
```http
GET /markets/sectors/banks/stocks
```

---

## MCP Tools (Alternative)

If using the MCP server instead of REST:

### List Industries
```python
await list_industries()
```

### List Sectors
```python
await list_sectors()
```

### Get Industry Stocks
```python
await get_industry_stocks(slug="bank-private")
```

### Get Sector Stocks
```python
await get_sector_stocks(slug="banks")
```

---

## Field Definitions

| Field | Type | Description |
|-------|------|-------------|
| `slug` | string | URL-friendly identifier (use in API calls) |
| `name` | string | Display name |
| `market_cap` | float | Total market cap in Rs Crores |
| `pe` | float | Industry/Sector PE ratio |
| `advance` | int | Number of advancing stocks |
| `decline` | int | Number of declining stocks |
| `sentiment` | string | Market sentiment (Bullish, Bearish, Neutral, Very Bullish, Very Bearish) |
| `earnings_yoy` | float | Year-over-year earnings change % |
| `curr_price` | float | Current stock price in Rs |
| `per_change` | float | Percentage change |
| `ttm_pe` | float | Trailing 12-month PE |
| `net_profit` | float | Latest net profit in Rs Cr |
| `net_profit_yoy` | float | Net profit YOY % |
| `tech_trend` | string | Technical trend indicator |
| `mc_url` | string | MoneyControl stock page URL |
| `categories` | array | List of categories the stock belongs to |

---

## Common Industry Slugs

| Industry | Slug |
|----------|------|
| Bank - Private | `bank-private` |
| IT Services & Consulting | `it-services-consulting` |
| Pharmaceuticals & Drugs | `pharmaceuticals-drugs` |
| Finance - NBFC | `finance-nbfc` |
| Automobiles | `automobiles` |

## Common Sector Slugs

| Sector | Slug |
|--------|------|
| Banks | `banks` |
| Finance | `finance` |
| IT Services | `software-it-services` |
| Healthcare | `healthcare` |
| FMCG | `fmcg` |

---

## Notes

- Stock symbols use MoneyControl's internal IDs (e.g., `HDF01` for HDFC Bank), not NSE ticker symbols
- The `categories` field shows all industries/sectors a stock belongs to
- Data is refreshed every 5 minutes during market hours
- On weekends, data refreshes every 2 hours
