# Ticker Warehouse API — Implementation Guide (v1)

> Document generated: 2026-04-13
> Base URL: `http://localhost:4455/api/ticker`

---

## Table of Contents

1. [Overview](#1-overview)
2. [Data Requirements](#2-data-requirements)
3. [Endpoints](#3-endpoints)
   - [3.1 Multi-Period Returns](#31-multi-period-returns)
   - [3.2 Universe & Sector Returns](#32-universe--sector-returns)
   - [3.3 52-Week Position](#33-52-week-position)
   - [3.4 Momentum Score](#34-momentum-score)
   - [3.5 Technical Indicators](#35-technical-indicators)
   - [3.6 Streak Tracking](#36-streak-tracking)
   - [3.7 Screener](#37-screener)
4. [Frontend Integration Guide](#4-frontend-integration-guide)
5. [Performance Notes](#5-performance-notes)
6. [Error Handling](#6-error-handling)

---

## 1. Overview

This document describes the ticker analytics endpoints implemented on top of the `ticker_daily` data warehouse. The endpoints provide:

- Multi-period return calculations (1D, 1W, 1M, 3M, 6M, 1Y)
- 52-week high/low positions (from NSE pre-calculated data, updated nightly)
- Composite momentum scoring with leaderboard
- Technical indicators (RSI, MACD, Bollinger Bands, ATR, VWMA, Historical Volatility, OBV, Sharpe)
- Streak tracking (consecutive up/down days, volume streaks, days since 52W high)
- Full-featured screener with 30+ filter options

**All endpoints use date-based lookups**, not row offsets — this ensures correctness for symbols with trading halts or recent IPOs.

**52W Data:** The 52-week high/low values are fetched from NSE's `nse_eq()` endpoint (`priceInfo.weekHighLow`) and stored in `stock_universe`. The `stock_universe_worker` job runs nightly at midnight to keep this data current.

---

## 2. Data Requirements

| Endpoint | Minimum Rows | Notes |
|----------|--------------|-------|
| Returns (1D) | 2 | Need at least yesterday + today |
| Returns (1W) | 6 | ~5 trading days |
| Returns (1M) | 21 | ~20 trading days |
| Returns (3M) | 61 | ~60 trading days |
| Returns (6M) | 121 | ~120 trading days |
| Returns (1Y) | 253 | ~252 trading days |
| Indicators | 60 | Required for MACD, RSI warmup |
| Momentum Score | 60 | For universe ranking |
| Screener | Any | Filters by data availability |

The `ticker_daily` table must have sufficient historical data (ideally 200+ rows per symbol) for full functionality.

---

## 3. Endpoints

### 3.1 Multi-Period Returns

#### GET `/returns/{symbol}`

Get multi-period returns for a single symbol.

**Request:**
```
GET /api/ticker/returns/RELIANCE
```

**Response:**
```json
{
  "symbol": "RELIANCE",
  "d1": 0.0,
  "d1w": 3.487391737564191,
  "d1m": -2.877283844051216,
  "d3m": -8.967098166127291,
  "d6m": -1.753620024739861,
  "d1y": 8.128453591735404,
  "latest_date": "2026-04-12"
}
```

**Field Mappings:**
- `d1` → 1-day return %
- `d1w` → 1-week return %
- `d1m` → 1-month return %
- `d3m` → 3-month return %
- `d6m` → 6-month return %
- `d1y` → 1-year return %

---

#### GET `/returns-bulk`

Get returns for multiple symbols in one call.

**Request:**
```
GET /api/ticker/returns-bulk?symbols=RELIANCE,TCS,INFY
```

**Response:**
```json
[
  {
    "symbol": "RELIANCE",
    "d1": 0.0,
    "d1w": 3.49,
    "d1m": -2.88,
    "d3m": -8.97,
    "d6m": -1.75,
    "d1y": 8.13,
    "latest_date": "2026-04-12"
  },
  {
    "symbol": "TCS",
    "d1": 0.0,
    "d1w": null,
    "d1m": null,
    "d3m": null,
    "d6m": null,
    "d1y": null,
    "latest_date": "2026-04-12"
  }
]
```

**Note:** Returns `null` for periods where insufficient data exists.

---

### 3.2 Universe & Sector Returns

#### GET `/universe-returns`

Get ranked returns across all symbols in the universe.

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| period | string | "1m" | Return period: 1d, 1w, 1m, 3m, 6m, 1y |
| sort_by | string | "return" | Field to sort by |
| order | string | "desc" | Sort order: asc or desc |
| limit | int | 50 | Max results (1-200) |

**Request:**
```
GET /api/ticker/universe-returns?period=1m&limit=10
```

**Response:**
```json
{
  "period": "1m",
  "count": 10,
  "results": [
    {
      "symbol": "MAHASTEEL",
      "return": 111.30361037072933,
      "latest_date": "2026-03-17"
    },
    {
      "symbol": "GVPIL",
      "return": 79.23258774322606,
      "latest_date": "2026-02-23"
    }
  ]
}
```

**Frontend Use:** Build a "Top Gainers" leaderboard or sector heatmap.

---

#### GET `/sector-returns`

Get average and median returns grouped by sector.

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| period | string | "1m" | Return period |

**Request:**
```
GET /api/ticker/sector-returns?period=1m
```

**Response:**
```json
{
  "period": "1m",
  "results": [
    {
      "sector": "Telecommunication",
      "avg_return": 28.60,
      "median_return": 28.60,
      "count": 1
    },
    {
      "sector": "Power",
      "avg_return": 9.44,
      "median_return": 8.10,
      "count": 12
    },
    {
      "sector": "Financial Services",
      "avg_return": 2.69,
      "median_return": 2.11,
      "count": 78
    }
  ]
}
```

**Frontend Use:** Sector rotation heatmap, sector breadth analysis.

---

### 3.3 52-Week Position

> **Note:** The ATH (All-Time High) endpoint was removed. 52W high/low is now fetched from NSE pre-calculated data and stored in `stock_universe`. See `stock_universe.high_52w`, `stock_universe.low_52w` columns.

#### GET `/position/52w/{symbol}`

Get 52-week high/low position from NSE pre-calculated data.

**Request:**
```
GET /api/ticker/position/52w/RELIANCE
```

**Response:**
```json
{
  "symbol": "RELIANCE",
  "high_52w": 1611.8,
  "low_52w": 1227.6,
  "high_52w_date": "2026-01-05",
  "low_52w_date": "2025-04-17",
  "current_close": 1350.2,
  "pct_from_52w_high": -16.24,
  "pct_from_52w_low": 9.99,
  "is_52w_high": false,
  "is_52w_low": false
}
```

**Fields:**
- `high_52w`, `low_52w`: 52-week high/low price from NSE
- `high_52w_date`, `low_52w_date`: Dates when the 52W high/low occurred
- `pct_from_52w_high`: Negative = below 52W high (e.g., -16% = 16% below high)
- `pct_from_52w_low`: Positive = above 52W low (e.g., 10% = 10% above low)
- `is_52w_high`: Boolean — is current close at or above 52W high?

**Data Source:** Values are fetched from NSE's `priceInfo.weekHighLow` in the `nse_eq()` endpoint and stored in `stock_universe` during the nightly `stock_universe_worker` job.

---

### 3.4 Momentum Score

#### GET `/momentum-score/{symbol}`

Get composite momentum score (0-100) with component breakdown.

**Request:**
```
GET /api/ticker/momentum-score/RELIANCE
```

**Response:**
```json
{
  "symbol": "RELIANCE",
  "score": 46.6,
  "rank": 196,
  "universe_size": 580,
  "reason": null,
  "components": {
    "rank_3m_return": 35.9,
    "rank_6m_return": 76.3,
    "rank_volume_ratio": 64.7
  }
}
```

**Scoring Formula:**
```
Score = 0.30 × rank_3m + 0.30 × rank_6m + 0.20 × rank_volume_ratio
```

- `rank_3m_return`: Percentile rank of 3-month return (0-100)
- `rank_6m_return`: Percentile rank of 6-month return (0-100)
- `rank_volume_ratio`: Percentile rank of volume ratio (today/20d avg)

**Interpretation:**
- Score > 80: Top momentum tier
- Score 60-80: Strong momentum
- Score 40-60: Neutral
- Score < 40: Weak momentum

---

#### GET `/momentum-leaderboard`

Get top N symbols by momentum score.

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| limit | int | 50 | Max results (1-200) |

**Request:**
```
GET /api/ticker/momentum-leaderboard?limit=10
```

**Response:**
```json
{
  "count": 10,
  "results": [
    {"rank": 1, "symbol": "APEX", "score": 79.5},
    {"rank": 2, "symbol": "LUMAXTECH", "score": 77.0},
    {"rank": 3, "symbol": "ABB", "score": 76.7},
    {"rank": 4, "symbol": "GVT&D", "score": 76.6},
    {"rank": 5, "symbol": "KIRLOSENG", "score": 76.4}
  ]
}
```

**Frontend Use:** Default "Top Momentum Stocks" widget, screener default sort.

---

### 3.5 Technical Indicators

#### GET `/indicators/{symbol}`

Get comprehensive technical indicators for a symbol.

**Request:**
```
GET /api/ticker/indicators/RELIANCE
```

**Response:**
```json
{
  "symbol": "RELIANCE",
  "data_points": 280,
  "latest_date": "2026-04-12",
  "close": 1350.2,
  "rsi_14": 43.33,
  "macd": -19.34,
  "macd_signal": -18.01,
  "macd_histogram": -1.32,
  "bb_middle": 1370.24,
  "bb_upper": 1438.99,
  "bb_lower": 1301.49,
  "bb_width": 10.03,
  "bb_squeeze": false,
  "atr_14": 33.46,
  "atr_percent": 2.48,
  "vwma_20": 1365.77,
  "hv_20": 28.33,
  "hv_60": 26.39,
  "obv": -21165939,
  "sharpe_60": -1.37,
  "sharpe_126": -0.11
}
```

**Indicator Details:**

| Indicator | Description | Notes |
|-----------|-------------|-------|
| `rsi_14` | RSI with Wilder smoothing | >70 overbought, <30 oversold |
| `macd` | MACD Line (EMA12 - EMA26) | Positive = bullish |
| `macd_signal` | Signal Line (EMA9 of MACD) | |
| `macd_histogram` | MACD - Signal | Expanding = strengthening |
| `bb_middle` | Bollinger Middle (SMA20) | |
| `bb_upper` | Bollinger Upper (+2 std) | |
| `bb_lower` | Bollinger Lower (-2 std) | |
| `bb_width` | BB Width % | Squeeze detection |
| `bb_squeeze` | True if at 126-day low | Compression before breakout |
| `atr_14` | Average True Range | |
| `atr_percent` | ATR / close × 100 | Normalised volatility |
| `vwma_20` | Volume-Weighted MA | Fair value proxy |
| `hv_20` | Historical Volatility (20d) | Annualised % |
| `hv_60` | Historical Volatility (60d) | |
| `obv` | On-Balance Volume | Cumulative |
| `sharpe_60` | Sharpe Ratio proxy (60d) | Risk-adjusted return |
| `sharpe_126` | Sharpe Ratio proxy (126d) | |

**Error Response (insufficient data):**
```json
{
  "symbol": "NEWSYMBOL",
  "error": "Insufficient data (45 rows, need 60+)",
  "data_points": 45
}
```

---

### 3.6 Streak Tracking

#### GET `/streaks/{symbol}`

Get streak metrics for a symbol.

**Request:**
```
GET /api/ticker/streaks/RELIANCE
```

**Response:**
```json
{
  "symbol": "RELIANCE",
  "consecutive_up_days": 0,
  "consecutive_down_days": 0,
  "consecutive_volume_up_days": 0,
  "days_since_52w_high": 100
}
```

**Fields:**
- `consecutive_up_days`: Days with close > previous close
- `consecutive_down_days`: Days with close < previous close
- `consecutive_volume_up_days`: Days with volume > 20-day avg
- `days_since_52w_high`: Calendar days since 52W high (from NSE data in `stock_universe`)

**Note:** The `days_since_ath` field was removed — 52W high date is now read from `stock_universe.high_52w_date`.

---

### 3.7 Screener

#### GET `/screener`

Run the full-featured screener with filters, sorting, and pagination.

**Query Parameters (Filters):**

| Parameter | Type | Description |
|-----------|------|-------------|
| pct_change_today_min/max | float | Today's % change |
| pct_change_1w_min/max | float | 1-week % change |
| pct_change_1m_min/max | float | 1-month % change |
| pct_change_3m_min/max | float | 3-month % change |
| pct_change_6m_min/max | float | 6-month % change |
| pct_change_1y_min/max | float | 1-year % change |
| volume_ratio_min/max | float | Today vol / 20d avg vol |
| pct_from_52w_high_min/max | float | % from 52W high |
| pct_from_52w_low_min/max | float | % from 52W low |
| is_52w_high | bool | Filter for 52W high |
| is_52w_low | bool | Filter for 52W low |
| atr_pct_min/max | float | ATR % (volatility) |
| rsi_min/max | float | RSI (14) |
| bb_squeeze | bool | Bollinger squeeze |
| pe_min/max | float | PE ratio |
| sector | string | Filter by sector (exact) |
| industry | string | Filter by industry (partial match) |
| above_sma50 | bool | Price above SMA50 |
| momentum_score_min | float | Min momentum score |
| min_data_points | int | Min rows required |

**Query Parameters (Sorting/Pagination):**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| sort_by | string | "symbol" | Field to sort by |
| order | string | "asc" | asc or desc |
| limit | int | 50 | Max results (1-200) |

**Request Examples:**

1. **Top gainers this month, near 52W high:**
```
GET /api/ticker/screener?pct_change_1m_min=5&pct_from_52w_high_max=10&sort_by=pct_change_1m&order=desc&limit=20
```

2. **High momentum + volume spike:**
```
GET /api/ticker/screener?momentum_score_min=70&volume_ratio_min=2&sort_by=momentum_score&order=desc&limit=20
```

3. **Low volatility stocks in IT sector:**
```
GET /api/ticker/screener?sector=Information Technology&atr_pct_max=2&sort_by=atr_percent&order=asc&limit=20
```

4. **Oversold stocks (RSI < 35):**
```
GET /api/ticker/screener?rsi_max=35&sort_by=rsi&order=asc&limit=20
```

5. **52W breakout stocks:**
```
GET /api/ticker/screener?is_52w_high=true&sort_by=change_today&order=desc&limit=20
```

**Response:**
```json
{
  "count": 27,
  "returned": 5,
  "filters_applied": ["pct_change_1m_min", "volume_ratio_min"],
  "results": [
    {
      "symbol": "ABREL",
      "close": 1361.1,
      "change_today": 4.44,
      "returns": {
        "symbol": "ABREL",
        "1d": 0.0,
        "1w": 15.47,
        "1m": 15.05,
        "3m": -13.27,
        "6m": -17.22,
        "1y": -30.37,
        "latest_date": "2026-04-12"
      },
      "pos_52w": {
        "high_52w": 2502.1,
        "low_52w": 1094.9,
        "high_52w_date": "2026-01-15",
        "low_52w_date": "2025-04-10",
        "pct_from_52w_high": -45.60,
        "pct_from_52w_low": 24.31,
        "is_52w_high": false
      },
      "volume_ratio": 1.23,
      "indicators": {
        "rsi_14": 52.33,
        "atr_percent": 3.45,
        "bb_squeeze": false
      },
      "sector": "Capital Goods",
      "industry": "Iron & Steel Products",
      "pe": 175.12,
      "data_points": 45
    }
  ]
}
```

**Note:** The `count` field shows total matching symbols; `returned` shows how many are returned (limited by `limit`).

---

## 4. Frontend Integration Guide

### 4.1 React Query Pattern

Use `@tanstack/react-query` for data fetching:

```tsx
// Example: Fetch returns for a symbol
const { data, isLoading, error } = useQuery({
  queryKey: ['ticker-returns', symbol],
  queryFn: () => fetch(`/api/ticker/returns/${symbol}`).then(r => r.json()),
  staleTime: 60000, // 1 minute
});
```

### 4.2 Widget Integration Map

| Widget Type | Primary Endpoint | Refresh Rate |
|-------------|------------------|--------------|
| Movers/Gainers | `/universe-returns?period=1m` | Daily (post-close) |
| Top Momentum | `/momentum-leaderboard` | Daily |
| Chart Panel | `/indicators/{symbol}` | On-demand |
| Watchlist Cards | `/returns-bulk?symbols=A,B,C` | On-demand |
| Volume Leaders | `/screener?volume_ratio_min=2` | Daily |
| Breakout Watch | `/screener?is_52w_high=true` | Daily |
| Oversold Radar | `/screener?rsi_max=35` | Daily |
| Sector Heatmap | `/sector-returns` | Daily |

### 4.3 Recommended Caching Strategy

| Endpoint | Cache Duration | Reason |
|----------|----------------|--------|
| `/returns/{symbol}` | 5 min | Changes daily |
| `/indicators/{symbol}` | 5 min | Changes daily |
| `/momentum-score/{symbol}` | 1 hour | Recalculated daily |
| `/momentum-leaderboard` | 1 hour | Expensive to compute |
| `/screener` | 5 min | Heavy computation |
| `/universe-returns` | 5 min | Changes daily |
| `/sector-returns` | 1 hour | Aggregated, slow-changing |

### 4.4 Screener UI Pattern

For screener results, fetch with filters and display in a table:

```tsx
const params = new URLSearchParams({
  pct_change_1m_min: '5',
  volume_ratio_min: '2',
  sort_by: 'pct_change_1m',
  order: 'desc',
  limit: '20',
});

const response = await fetch(`/api/ticker/screener?${params}`);
// response.results[] contains full symbol data
```

### 4.5 Combining Multiple Endpoints

For a dashboard view, make parallel requests:

```tsx
const [returns, indicators, streaks] = await Promise.all([
  fetch(`/api/ticker/returns/${symbol}`).then(r => r.json()),
  fetch(`/api/ticker/indicators/${symbol}`).then(r => r.json()),
  fetch(`/api/ticker/streaks/${symbol}`).then(r => r.json()),
]);

// Combine into single display object
const dashboardData = {
  ...returns,
  ...indicators,
  ...streaks,
};
```

---

## 5. Performance Notes

1. **Screener Caching:** The screener caches results for 5 minutes internally. Set `use_cache=true` (default) for faster subsequent calls. Call `invalidate_cache()` if you need fresh data after a daily update.

2. **Bulk Requests:** Use `/returns-bulk?symbols=A,B,C` instead of multiple individual calls.

3. **Indicator Minimums:** Don't call `/indicators/` for symbols with < 60 rows — it will return an error. Check `data_points` in other responses to estimate availability.

4. **Rate Limiting:** The backend has no rate limiting on these endpoints. However, heavy screener use (full universe scan) should be done sparingly — cache on the frontend.

5. **Data Freshness:** All calculations use the latest data in `ticker_daily`. Ensure the daily update job has run before displaying live data.

---

## 6. Error Handling

All endpoints return appropriate HTTP status codes:

| Status | Meaning |
|--------|---------|
| 200 | Success |
| 400 | Invalid parameter (e.g., invalid date format) |
| 404 | Symbol not found in database |
| 500 | Internal error (check server logs) |

**Error Response Examples:**

```json
// 404 - Symbol not in ticker_daily
{"detail": "Not Found"}

// 400 - Invalid query parameter
{"detail": "Invalid from_date format. Use DD-MM-YYYY"}
```

**Frontend:** Always wrap API calls in try/catch and display user-friendly error messages.

---

## 7. File Locations

| File | Purpose |
|------|---------|
| `app/services/returns.py` | Returns, positions, streaks |
| `app/services/momentum.py` | Momentum score calculation |
| `app/services/indicators.py` | Technical indicator calculations |
| `app/services/screener.py` | Screener logic with caching |
| `app/routers/ticker.py` | HTTP endpoints |

---

*End of document.*