# Ticker Warehouse — Ideas for Extracting Insights

This document catalogs all possible analytical features that can be built using the data stored in the `ticker_daily` table, assuming the full backfill is complete (~200+ rows per symbol, typically 280 trading days of history).

---

## 1. Data Model Summary

### Current Schema: `ticker_daily`

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| symbol | VARCHAR(32) | NSE ticker symbol |
| date | DATE | Trading date |
| series | VARCHAR(4) | EQ, BE, etc. (default EQ) |
| open | FLOAT | Opening price |
| high | FLOAT | Intraday high |
| low | FLOAT | Intraday low |
| close | FLOAT | Closing price |
| volume | BIGINT | Total traded quantity |
| value | FLOAT | Total traded value (₹) |
| source | VARCHAR(32) | bhavcopy or equity_history |
| created_at | DATETIME | Row creation timestamp |

### Available Metadata (Joinable)

1. **stock_universe**
   - `symbol`, `company_name`
   - `industry_info` (JSON: macro, sector, industry, basicIndustry)
   - `symbol_pe` (PE ratio, available for ~678 symbols)

2. **market_category_stocks**
   - `symbol`, `company_name`, `exchange`
   - `curr_price`, `per_change`
   - `market_cap`, `ttm_pe`
   - `tech_trend` (Bullish, Bearish, Neutral, Very Bullish, Very Bearish)

---

## 2. Technical Indicators

Computed on the fly from OHLCV. No additional storage needed.

### 2.1 Moving Averages

| Indicator | Formula | Use |
|-----------|---------|-----|
| SMA 20 | mean(close, 20) | Short-term trend |
| SMA 50 | mean(close, 50) | Medium-term trend |
| SMA 200 | mean(close, 200) | Long-term trend |
| EMA 12 | exponential moving average | Fast MACD component |
| EMA 26 | exponential moving average | Slow MACD component |

**Signals:**
- Price above SMA50 → medium-term bullish
- Price above SMA200 → long-term bullish
- SMA50 crossing above SMA200 → Golden Cross (bullish)
- SMA50 crossing below SMA200 → Death Cross (bearish)

### 2.2 MACD (Moving Average Convergence Divergence)

| Component | Formula |
|-----------|---------|
| MACD Line | EMA12 - EMA26 |
| Signal Line | EMA9(MACD) |
| Histogram | MACD - Signal |

**Signals:**
- MACD crosses above Signal → bullish momentum
- MACD crosses below Signal → bearish momentum
- Histogram expanding → strengthening momentum

### 2.3 RSI (Relative Strength Index)

| Parameter | Formula |
|-----------|---------|
| RSI 14 | 100 - 100/(1 + RS), where RS = avg gain / avg loss over 14 periods |

**Interpretation:**
- RSI > 70: Overbought, potential reversal
- RSI < 30: Oversold, potential bounce
- RSI > 50: Bullish bias
- RSI < 50: Bearish bias

**Implementation:** Calculate using rolling windows on sorted close prices.

### 2.4 Bollinger Bands

| Component | Formula |
|-----------|---------|
| Middle | SMA20 |
| Upper | Middle + 2 × stddev(close, 20) |
| Lower | Middle - 2 × stddev(close, 20) |

**Signals:**
- Price touching Upper → overbought
- Price touching Lower → oversold
- Squeeze (bands narrowing) → compression, potential breakout

### 2.5 ATR (Average True Range)

| Component | Formula |
|-----------|---------|
| TR | max(high - low, |high - prev_close|, |low - prev_close|) |
| ATR 14 | mean(TR, 14) |

**Use:** Normalise volatility for position sizing. High ATR% = high volatility.

### 2.6 Historical Volatility

| Component | Formula |
|-----------|---------|
| HV20 | stddev(log(close_t/close_(t-1))) × sqrt(252) × 100 |
| HV60 | stddev(log(close_t/close_(t-1))) × sqrt(252) × 100 |

**Use:** Options pricing, risk management. Compare HV20 vs HV60 to detect vol expansion.

### 2.7 OBV (On-Balance Volume)

| Component | Formula |
|-----------|---------|
| OBV | cumulative sum of volume where close > prev_close, -volume when close < prev_close |

**Use:** Volume-price divergence. Price falling but OBV rising = accumulation (bullish).

### 2.8 VWAP (Volume Weighted Average Price)

| Component | Formula |
|-----------|---------|
| VWAP | sum(close × volume) / sum(volume) for rolling N days |

**Intraday use:** Fair value proxy. Price above VWAP = expensive, below = cheap.

---

## 3. Screener Filters

The most valuable terminal feature — filter the entire universe at once.

### 3.1 Price Action Filters

| Filter | Field | Example Values |
|--------|-------|----------------|
| % change today | (close - open) / open × 100 | > 3%, < -2% |
| % change 1W | (close - close_5d) / close_5d × 100 | top 20 |
| % change 1M | (close - close_20d) / close_20d × 100 | top 20 |
| % change 3M | (close - close_60d) / close_60d × 100 | top 20 |
| % change 6M | (close - close_120d) / close_120d × 100 | top 20 |
| % change 1Y | (close - close_252d) / close_252d × 100 | top 20 |

### 3.2 Volume Filters

| Filter | Field | Formula |
|--------|-------|--------|
| Volume ratio | today_vol / avg_vol_20d | > 2.0 = unusual |
| Value traded | sum(value, N days) | filter by liquidity |
| Value spike ratio | today_value / avg_value_20d | > 1.5 |

### 3.3 52-Week Position

| Filter | Field | Formula |
|--------|-------|--------|
| % from 52W high | (close - 52w_high) / 52w_high × 100 | < 5% = near breakout |
| % from 52W low | (close - 52w_low) / 52w_low × 100 | > 200% = recovered |
| 52W high flag | close >= 52w_high | = true = at new high |
| 52W low flag | close <= 52w_low | = true = at new low |

### 3.4 Trend Filters

| Filter | Values |
|--------|--------|
| Above SMA50 | close > SMA50 |
| Below SMA50 | close < SMA50 |
| Golden Cross (last N days) | SMA50 > SMA200 for N consecutive days |
| Death Cross (last N days) | SMA50 < SMA200 for N consecutive days |

### 3.5 Volatility Filters

| Filter | Field | Formula |
|--------|-------|--------|
| ATR% | ATR14 / close × 100 | < 2% = low vol |
| ATR% rank | percentile rank of ATR% across universe | < 20% = consolidating |

### 3.6 Valuation Filters (Join with stock_universe)

| Filter | Field |
|--------|-------|
| PE less than | symbol_pe < 15 |
| PE greater than | symbol_pe > 25 |
| PE in range | 15 <= symbol_pe <= 25 |

### 3.7 Sector/Industry Filters (Join with stock_universe)

| Filter | Field |
|--------|-------|
| Sector equals | industry_info->>'$.sector' = 'IT' |
| Industry contains | industry_info->>'$.industry' like '%Banking%' |
| Macro sector | industry_info->>'$.macro' = 'Financial Services' |

### 3.8 Technical Trend Filters (Join with market_category_stocks)

| Filter | Field |
|--------|-------|
| Tech trend | tech_trend = 'Bullish' |
| Tech trend | tech_trend = 'Very Bearish' |

### 3.9 Composite Screener (Example Payload)

```json
GET /api/ticker/screener?filters={
  "pct_change_1m_min": 5,
  "volume_ratio_min": 1.5,
  "pct_from_52w_high_max": 10,
  "atr_pct_max": 3.0,
  "sector": "IT",
  "sort_by": "pct_change_1m",
  "order": "desc",
  "limit": 20
}
```

Returns top 20 IT stocks with 5%+ 1-month return, volume spike >1.5x, within 10% of 52W high, low volatility.

---

## 4. Multi-Period Returns

Single endpoint to retrieve all standard return periods for one symbol or bulk for multiple.

### 4.1 Return Periods

| Period | Calculation | Trading Days |
|--------|------------|-------------|
| 1D | (close - prev_close) / prev_close × 100 | 1 |
| 1W | (close - close_5d) / close_5d × 100 | 5 |
| 1M | (close - close_20d) / close_20d × 100 | 20 |
| 3M | (close - close_60d) / close_60d × 100 | 60 |
| 6M | (close - close_120d) / close_120d × 100 | 120 |
| 1Y | (close - close_252d) / close_252d × 100 | 252 |

### 4.2 Endpoints

```json
GET /api/ticker/returns/{symbol}
// Response:
{
  "symbol": "RELIANCE",
  "1d": 1.23,
  "1w": -2.45,
  "1m": 5.67,
  "3m": 12.34,
  "6m": 23.45,
  "1y": 45.67,
  "latest_date": "2026-04-10"
}

GET /api/ticker/returns-bulk?symbols=RELIANCE,TCS,INFY
// Returns array of return objects for multiple symbols
```

### 4.3 Universe Return Heatmap

```json
GET /api/ticker/universe-returns?period=1m&sort_by=return&order=desc&limit=50
// Top 50 performers ranked by 1-month return
```

### 4.4 Sector Return Aggregation

Join `ticker_daily` → `stock_universe` → extract `industry_info->>'$.sector'` as sector.

```json
GET /api/ticker/sector-returns?period=1m
// Response:
[
  { "sector": "IT", "avg_return": 4.5, "count": 45 },
  { "sector": "Financial Services", "avg_return": 2.3, "count": 89 },
  { "sector": "Pharmaceuticals", "avg_return": -1.2, "count": 34 }
]
```

---

## 5. Relative Strength

### 5.1 Relative Strength vs Index

| Metric | Formula |
|--------|---------|
| RS (N days) | (symbol_return_Nd / index_return_Nd) - 1 |

- RS > 0: Outperforming the index
- RS < 0: Underperforming
- RS ranking across universe: momentum leaderboard

### 5.2 Sector Relative Strength

Within a sector, compare each stock's return to sector average.

### 5.3 Endpoint

```json
GET /api/ticker/relative-strength/{symbol}?vs=NIFTY50&period=3m
// Response: { "symbol": "RELIANCE", "vs": "NIFTY50", "period": "3m", "rs": 0.15 }
// RS of 0.15 = 15% better than NIFTY50 over 3 months
```

---

## 6. Volume Analysis

### 6.1 Volume Spike Detection

| Metric | Formula |
|--------|---------|
| Volume ratio | today_vol / mean(volume, last 20 days) |
| Volume spike flag | ratio > 2.0 |
| Unusual volume alert | ratio > 3.0 |

### 6.2 Value Traded (Liquidity Proxy)

| Metric | Formula |
|--------|---------|
| Avg daily value | sum(value, last 20 days) / 20 |
| Value rank | percentile rank of avg_daily_value across universe |

Use: Filter out illiquid stocks from screener (e.g., avg_daily_value > ₹10Cr).

### 6.3 Money Flow

| Metric | Formula |
|--------|---------|
| Value change | value_today / value_5d_avg - 1 |
| Price × volume divergence | (close - open) × volume direction |

If price closes lower but volume is 2x average → distribution (smart money selling).

---

## 7. Gap Analysis

### 7.1 Gap Calculation

| Metric | Formula |
|--------|---------|
| Gap % | (open - prev_close) / prev_close × 100 |
| Gap type | Gap up (> 0.5%), Gap down (< -0.5%), No gap |

### 7.2 Gap Fill Detection

Did the stock fill the intraday gap?

| Metric | Description |
|--------|-------------|
| Gap filled | low <= prev_close (for gap up) or high >= prev_close (for gap down) |
| Gap retained | price closed in same direction as gap |

### 7.3 Gap Statistics per Symbol

| Metric | Value |
|--------|-------|
| Gap frequency | % of days with gap > 0.5% |
| Avg gap size | mean of |gap%| for gaps only |
| Gap fill rate | % of gaps that filled by EOD |

### 7.4 Endpoint

```json
GET /api/ticker/gaps/{symbol}/last=30
// Response: { "symbol": "RELIANCE", "gaps": [...] }
```

---

## 8. Candle Pattern Detection

Simple rules from OHLCV relationships.

### 8.1 Basic Patterns

| Pattern | Condition |
|---------|-----------|
| Doji | |open - close| / (high - low) < 0.1 |
| Hammer | body in upper 25% of range, lower wick > 2× body |
| Shooting Star | body in lower 25% of range, upper wick > 2× body |
| Marubozu | body > 90% of total range |

### 8.2 Multi-Day Patterns

| Pattern | Condition |
|---------|-----------|
| Inside Bar | high_t < high_(t-1) and low_t > low_(t-1) |
| Outside Bar | high_t > high_(t-1) and low_t < low_(t-1) |
| NR7 | range_t = min(range_(t-6:t)), all within previous 7-day range |
| Bullish Engulfing | close_t > open_t, close_(t-1) < open_(t-1), body_t engulfs body_(t-1) |
| Bearish Engulfing | close_t < open_t, close_(t-1) > open_(t-1), body_t engulfs body_(t-1) |

### 8.3 Endpoint

```json
GET /api/ticker/patterns/{symbol}?days=30
// Response: { "symbol": "RELIANCE", "patterns": [{ "date": "2026-04-10", "pattern": "hammer" }, ...] }
```

---

## 9. Sector / Industry Aggregation

### 9.1 Sector Breadth

For each sector, what % of stocks are above their SMA50?

| Metric | Formula |
|--------|---------|
| Stocks above SMA50 | count(close > SMA50) / count(sector) × 100 |
| Bullish breadth | > 60% = strong sector |
| Bearish breadth | < 40% = weak sector |

### 9.2 Sector Rotation Heatmap

Rank sectors by average 1M return. Identify which macro sectors are leading/lagging.

```json
GET /api/ticker/sector-rotation?period=1m
// Response: [ { "sector": "IT", "avg_return": 4.5 }, { "sector": "Energy", "avg_return": 1.2 }... ]
```

### 9.3 Intra-Sector Relative Strength

Within each sector, rank stocks by 3M return vs sector average.

---

## 10. Fair Value Overlay

**Note:** The `stock_universe.fair_value` column exists but is currently empty. This section assumes it will be populated via Morningstar data.

### 10.1 Margin of Safety

| Metric | Formula |
|--------|---------|
| Margin of Safety | (fair_value - close) / fair_value × 100 |

- MOS > 20%: significantly undervalued
- MOS > 50%: deep value

### 10.2 Screener Addition

```json
GET /api/ticker/screener?filters={ "mos_min": 20, "rs_3m_min": 0 }
```

Unders + positive momentum = high-conviction value play.

---

## 11. Notification Triggers

Wire these to the existing `notifications` table.

### 11.1 Price-Based Triggers

| Trigger | Condition |
|---------|-----------|
| 52W high breakout | close > max(close, 252 days) |
| 52W low breakdown | close < min(close, 252 days) |
| Gap up > X% | gap_pct > 3% |
| Gap down > X% | gap_pct < -3% |

### 11.2 Volume-Based Triggers

| Trigger | Condition |
|---------|-----------|
| Volume spike | today_vol / avg_vol_20d > 3.0 |
| Volume collapse | today_vol / avg_vol_20d < 0.2 |

### 11.3 Technical Indicator Triggers

| Trigger | Condition |
|---------|-----------|
| RSI crosses 30 | RSI_(t-1) >= 30 and RSI_t < 30 (oversold bounce) |
| RSI crosses 70 | RSI_(t-1) <= 70 and RSI_t > 70 (overbought) |
| Golden Cross | SMA50 crosses above SMA200 |
| Death Cross | SMA50 crosses below SMA200 |
| Price crosses SMA200 | close crosses above/below SMA200 |

### 11.4 Implementation

Add a background worker that runs after daily update and checks these conditions for all symbols, inserting into `notifications` where conditions are met.

---

## 12. Correlation & Portfolio Tools

### 12.1 Correlation Matrix

Compute pairwise correlation of daily returns for universe.

| Metric | Formula |
|--------|---------|
| Correlation | correlation(symbol_a_returns, symbol_b_returns) |

**Use:** Find pairs that move together (for pairs trading) or inversely (for hedging).

### 12.2 Beta to Nifty

| Metric | Formula |
|--------|---------|
| Beta | covariance(symbol_returns, nifty_returns) / variance(nifty_returns) |

- Beta > 1: aggressive (moves more than market)
- Beta < 1: defensive (moves less than market)

### 12.3 Drawdown Analysis

| Metric | Formula |
|--------|---------|
| Max Drawdown | (peak - trough) / peak × 100 for rolling N days |
| Days to Recovery | days from trough back to previous peak |

### 12.4 Endpoint

```json
GET /api/ticker/drawdowns/{symbol}?window=252
// Returns max drawdown and recovery time over 252 days
```

---

## 13. Implementation Priority

Ordered by value-to-effort ratio for this terminal.

| Priority | Feature | Complexity | Value |
|----------|---------|------------|-------|
| 1 | Multi-period returns endpoint | Low | High |
| 2 | Screener (price/volume/52W) | Medium | Very High |
| 3 | 52W high/low position | Low | High |
| 4 | Volume spike detection → alerts | Low | High |
| 5 | Technical indicators endpoint | Medium | High |
| 6 | Sector aggregation | Medium | High |
| 7 | Sector rotation heatmap | Medium | High |
| 8 | Multi-symbol returns heatmap | Low | Medium |
| 9 | RSI endpoint | Low | Medium |
| 10 | Gap analysis | Low | Medium |
| 11 | Candle patterns | Medium | Medium |
| 12 | MA crossover notifications | Medium | High |
| 13 | Relative strength vs index | Medium | Medium |
| 14 | Correlation matrix | High | Medium |
| 15 | Fair value overlay | Low | Very High (when data exists) |

---

## 14. File Locations

### Backend Files

| File | Purpose |
|------|---------|
| `app/models/ticker.py` | ORM model |
| `app/schemas/ticker.py` | Pydantic schemas |
| `app/routers/ticker.py` | HTTP endpoints |
| `app/services/ticker_warehouse.py` | Data access layer |
| `app/backgroundtasks.py` | Background workers |

### Planned New Files (for insights)

| File | Purpose |
|------|---------|
| `app/services/indicators.py` | Technical indicator calculations |
| `app/services/screener.py` | Screener logic |
| `app/services/returns.py` | Multi-period returns |
| `app/services/notifications.py` | Notification trigger checks |
| `app/routers/screener.py` | Screener endpoint |
| `app/routers/returns.py` | Returns endpoint |
| `app/routers/indicators.py` | Indicators endpoint |

---

## 15. API Design Summary

### Existing Endpoints

| Endpoint | Returns |
|----------|--------|
| `GET /api/ticker/ohlcv/{symbol}` | OHLCV rows in date range |
| `GET /api/ticker/ohlcv/{symbol}/latest` | Single latest candle |
| `GET /api/ticker/status` | Warehouse statistics |
| `POST /api/ticker/trigger-backfill` | Trigger background backfill |
| `POST /api/ticker/trigger-daily-update` | Trigger background update |

### Proposed Endpoints

| Endpoint | Returns |
|----------|--------|
| `GET /api/ticker/returns/{symbol}` | Multi-period returns |
| `GET /api/ticker/returns-bulk` | Returns for multiple symbols |
| `GET /api/ticker/universe-returns` | Ranked returns heatmap |
| `GET /api/ticker/sector-returns` | Average returns by sector |
| `GET /api/ticker/screener` | Filtered symbol list |
| `GET /api/ticker/indicators/{symbol}` | Technical indicators |
| `GET /api/ticker/gaps/{symbol}` | Gap analysis |
| `GET /api/ticker/patterns/{symbol}` | Candle patterns |
| `GET /api/ticker/relative-strength/{symbol}` | RS vs index |
| `GET /api/ticker/drawdowns/{symbol}` | Max drawdown |
| `POST /api/ticker/check-triggers` | Run notification checks |

---

## 16. Notes

- All calculations can be done via SQL window functions or in-memory pandas within request handlers.
- For Screener covering 2000+ symbols, consider caching results and invalidating after daily update.
- Period calculations assume ~252 trading days per year, ~21 per month, ~5 per week.
- Some metrics (correlation matrix) are computationally expensive — run as background job and cache.
- The `industry_info` JSON field can be queried via SQLite JSON extract functions for sector filtering.

---

*Document prepared for BLM Terminal. Last updated: 2026-04-11.*